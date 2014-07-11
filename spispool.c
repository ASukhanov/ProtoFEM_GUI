/* SPI reader
*
*   2014-07-10  AS, Version 1.
*   2014-07-11  AS. V2. spi_speed = 8MHz, delayEv=1ms
*/
char* gVersion = "2";

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define SPI_ENGINE_WPI 1
#define SPI_ENGINE_FTDI 2
#define SPI_ENGINE SPI_ENGINE_WPI

#if SPI_ENGINE == SPI_ENGINE_WPI
#include <wiringPi.h>
#include <wiringPiSPI.h>
int spi_open(int ch, int speed)
{
    int rc;
    rc = wiringPiSPISetup (ch, speed) ;
    if(rc==-1)
    {
        printf("ERROR in wiringPiSPISetup\n");
        exit(-1);
    }
    return rc;
}
int spi_read(int ch, unsigned char* data, int len)
{
    return wiringPiSPIDataRW (ch, data, len) ;
}
int spi_close()
{
    return 0;
}
void delay_ms(int ms)
{
    delay(ms);
}
char *gDirName = "/run/shm/";
#endif

#if SPI_ENGINE == SPI_ENGINE_FTDI
#include <mpsse.h>
#endif

typedef unsigned short WORD;
typedef unsigned long DWORD;

int gEvN = 0;
int gExtraWords = 0;

#define VERB_MLOG 1	//minimal log
#define VERB_ERR 2	//errors
#define VERB_DUMP 4	//extended log
#define VERB_XLOG 8	//dump
int verbosity = 3;


void dumpbuf(unsigned char *buf, int nbytes)
{
    int ii;
    printf("0x0000:");
    for(ii=0;ii<nbytes;ii++)
    {
        printf("%02x ",buf[ii]);
        if((ii%32) == 31) printf("\n0x%04x:",ii+1);
    }
    printf("\n");
}
int trim_event(unsigned char *data)
#define EVOFFSET 4
{
    // Trim event to the length, calculated from the header.
    // Return event length or -1 when stop run is found.
    int evl=0;
    int fevhl=0, fevtl=0, fevnasics=0, fevchains=0;
    #define BYTES_PEE_ASIC 129

    data += EVOFFSET; //skip 2 empty bytes
    if(data[4] == 0)    return 0;
    //check if header is correct
    if(data[4] != 0xf0 || data[5] != 0xc1) 
    {
        if(data[0]==0xff && data[1]==0xff) return -1;   //all ff's - run stopped
        if(verbosity & VERB_ERR) printf("ERROR in event format, event %d, ID: %02x%02x\n",gEvN,data[4],data[5]);
        return 0;
    }
    fevhl = data[11]&0xf;
    fevtl = ((data[11])>>4)&0xf;
    fevnasics = ((data[3])>>4)&0xf;
    fevchains = data[3]&0xf;
    evl = (fevhl + fevtl + gExtraWords)*2 + fevnasics*BYTES_PEE_ASIC;
    if(verbosity & VERB_DUMP) printf("hl=%i. tl=%i, na=%i, nc=%i, el=%i\n",fevhl, fevtl, fevnasics, fevchains, evl); 
    //check, if trailer is correct
    if((data[evl-4] != 0xfe) || (data[evl-3] != 0x0d))
    {
        if(verbosity & VERB_ERR) printf("ERROR. Event trailer wrong %02x%02x != fe0d\n",data[evl-4],data[evl-3]);
    }
    return evl;
}

int main(int argc, char **argv)
{
    int rc;
    int nFiles=1, nEvents=0;
    int nBytes=290; //2 SVX4s + 4
    #define BUFSIZE 2048
    unsigned char buf[BUFSIZE];
    unsigned char *pdata = buf;
    int spi_speed = 8000000; // SPI clock frequency, 8 MHz is OK with short cable. 0.5 MHz is minimal;
    int delayEv   = 1;	     // Delay between polling for event in ms, 1 is good for 8 MHz cloc
    int spi_channel = 0;
    int help = 0;
    int trim_events = 0;
    int writing_enabled = 1;
    FILE *ff = NULL;
    int filesize = 0;
    time_t tmt,curtim;
    double seconds;
    int prevEvN=0;
    struct tm * timeptr;
    int arg;
    #define FNSIZE 128
    char filename[FNSIZE] ={0};
    char pathname[FNSIZE] ={0};
    #define DNSIZE 40
    char dirname[DNSIZE];
    char lastfn[40];
    //unsigned int prevMillis=0,curMillis,diffMillis;

    strncpy(dirname,gDirName,DNSIZE);
    for (arg = 1; arg < argc; arg++)
    {
        if (argv[arg][0] == '-')
        {
            switch(toupper(argv[arg][1]))
            {
            case 'V':
                sscanf(&argv[arg][2], "%ld", &verbosity);
                break;
            case 'F':
                sscanf(&argv[arg][2], "%ld", &nFiles);
                break;
            case 'L':
                sscanf(&argv[arg][2], "%ld", &nBytes);
                break;
            case 'E':
                sscanf(&argv[arg][2], "%ld", &nEvents);
                break;
            case 'T':
                printf("Trimming enabled.\n");
                trim_events = 1;
                break;
            case 'W':
                writing_enabled = 0;
                printf("Recording disabled.\n");
                break;
            case 'H':
                help = 1;
                break;
            case 'P':
                sscanf(&argv[arg][2], "%ld", &delayEv);
                break;
            case 'S':
                sscanf(&argv[arg][2], "%ld", &spi_speed);
                break;
            case 'D':
                strncpy(dirname,&(argv[arg][2]),DNSIZE);
                break;
            case 'X':
                sscanf(&argv[arg][2], "%ld",&gExtraWords);
		printf("Expecting %i extra words in event.\n",gExtraWords);
                break;
            default:
                break;
            }
        }
    }
    if(help || argc == 1)
    {
       printf("SPI Recorder for Raspberry Pi, version %s\n",gVersion);
       printf("Usage:  spispool [options]\n");
       printf( "   Available options:\n");
       printf( "   -h  : show help message\n");
       printf( "   -vN : verbosity level\n");
       printf( "   -fN : number of files to read, default: 1\n");
       printf( "   -eN : number of transfers (events)per file\n");
       printf( "   -lN : max length of the transfer, default: %i\n",nBytes);
       printf( "   -pN : pause between events in milliseconds\n");
       printf( "   -sN : SPI clock frequency 500,000 (default) through 32,000,000\n");
       printf( "   -t  : trim events to correct size\n");
       printf( "   -w  : disable writing to file\n");
       printf( "   -dT : data directory, default: /run/shm\n");
       printf( "   -xN : number of extra words in the event\n");
       return(0);
    }

    if(writing_enabled) 
        printf("Recording %i files with %i events[%i] per file to directory %s\n",nFiles,nEvents,nBytes,dirname);
    spi_open(spi_channel,spi_speed);
    printf("Delay between events %i ms.\n",delayEv);
    printf("Verbosity %i.\n",verbosity);

    for(nFiles;nFiles>0;nFiles--)
    {
	prevEvN = 0;
	time(&tmt);
        //prevMillis = millis();
        if(nEvents<1) nEvents = 1;
        if (writing_enabled)
        {
            timeptr = localtime(&tmt);
            snprintf(filename,FNSIZE,"%.2d%.2d%.2d%.2d%.2d%.2d.dq4",
                timeptr->tm_year-100,
                timeptr->tm_mon+1,
                timeptr->tm_mday, timeptr->tm_hour,
                timeptr->tm_min,timeptr->tm_sec);
	    strcpy(pathname,dirname);
	    strncat(pathname,filename,FNSIZE-strlen(dirname));
            ff = fopen(pathname,"w");
	    if(ff==NULL) 
	    {
		printf("ERROR opening file %s\n",pathname);
		strcpy(pathname,"not open");
		exit(-2);
	    }
        }
        if(verbosity & VERB_MLOG) printf("File %s, %i files to go.\n",pathname,nFiles);
        for(gEvN=-1;gEvN<nEvents-1;)
        {
            if(verbosity & VERB_XLOG) printf("record %i\n",gEvN);
            rc = spi_read(spi_channel,buf,nBytes);
            if(verbosity & VERB_XLOG) dumpbuf(buf, rc);
            if(delayEv)   delay_ms(delayEv);
            if(trim_events) rc = trim_event(buf);
            pdata = buf + EVOFFSET;
            if(rc ==  0)  continue;
            if(rc == -1)
            {
                if(gEvN > 0)  
                {
                    printf("DAQ run %s stopped by operator after %i events\n",filename,gEvN);
                    break;   //run stopped
                }
                if(gEvN < 0) { gEvN = 0 ; printf("DAQ run not started\n");}
            }
            else gEvN++;
            if(gEvN == 1) printf("DAQ run started\n");
            if((gEvN % 100)==1)
            {
                time(&curtim);
                seconds = difftime(curtim,tmt);
		if(seconds>=10.) 
                {
                   tmt = curtim;
                   if(verbosity & VERB_MLOG) printf("Event %i[%i], %.1f ev/s\n",gEvN,rc,(double)(gEvN-prevEvN)/seconds);
                   prevEvN=gEvN;
                }
            }
            if(rc<=0) continue;
            if(verbosity & VERB_DUMP) printf("Event %i[%i]\n",gEvN,rc);
            if(verbosity & VERB_DUMP) dumpbuf(pdata, rc);
            if(ff) fwrite(pdata,1,rc,ff);
        }
        if(ff) 
        {
            fseek(ff,0L,SEEK_END);
            filesize = ftell(ff);
            fclose(ff);
            // Inform analyzer that we have a fresh file
            snprintf(lastfn,40,"%sdaqcapture.dq0",dirname);
            ff = fopen(lastfn,"w");
            fwrite(filename,1,strlen(filename),ff);
            if(ff) fclose(ff);
            printf("File %s[%i] written\n",filename,filesize);
        }
    }
    spi_close();
}
