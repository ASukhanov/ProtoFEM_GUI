/* SPI reader
*
*   2014-06-18  AS
*/

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

unsigned int gEvN = 0;
int gExtraWords = 0;
int verbosity = 0;

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
        printf("ERROR in event format, event %d, ID: %02x%02x\n",gEvN,data[4],data[5]);
        return 0;
    }
    fevhl = data[11]&0xf;
    fevtl = ((data[11])>>4)&0xf;
    fevnasics = ((data[3])>>4)&0xf;
    fevchains = data[3]&0xf;
    evl = (fevhl + fevtl + gExtraWords)*2 + fevnasics*BYTES_PEE_ASIC;
    if(verbosity&8) printf("hl=%i. tl=%i, na=%i, nc=%i, el=%i\n",fevhl, fevtl, fevnasics, fevchains, evl); 
    //check, if trailer is correct
    if((data[evl-4] != 0xfe) || (data[evl-3] != 0x0d))
    {
        printf("ERROR. Event trailer wrong %02x%02x != fe0d\n",data[evl-4],data[evl-3]);
    }
    return evl;
}

int main(int argc, char **argv)
{
    int rc;
    int nFiles=1, nEvents=1, nBytes=512;
    #define BUFSIZE 2048
    unsigned char buf[BUFSIZE];
    unsigned char *pdata = buf;
    int spi_speed = 500000, spi_channel = 0;
    int help = 0;
    int trim_events = 0;
    int writing_enabled = 1;
    FILE *ff = NULL; 
    int filesize = 0;
    time_t tmt;
    struct tm * timeptr;
    int delay=0;
    int arg;
    #define FNSIZE 128
    char filename[FNSIZE] ={0};
    char pathname[FNSIZE] ={0};
    #define DNSIZE 40
    char dirname[DNSIZE];
    char lastfn[40];
    
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
                printf("Trimming enabled\n");
                trim_events = 1;
                break;
            case 'W':
                writing_enabled = 0;
                break;                          
            case 'H':
                help = 1;
                break;
            case 'P':
                sscanf(&argv[arg][2], "%ld", &delay);
                break;
            case 'S':
                sscanf(&argv[arg][2], "%ld", &spi_speed);
                break;
            case 'D':
                strncpy(dirname,&(argv[arg][2]),DNSIZE);
                break;
            case 'X':
                sscanf(&argv[arg][2], "%ld",&gExtraWords);
                break;
            default:
                break;
            }
        }
        if(help)
        {
            printf("SPI Recorder\n");
            printf("Usage:  spispool [options]\n");
            printf( "   Available options:\n");
            printf( "   -h  : show help message\n");
            printf( "   -vN : verbosity level\n");
            printf( "   -fN : number of files to read\n");
            printf( "   -eN : number of transfers (events)per file\n");
            printf( "   -lN : max length of the transfer\n");
            printf( "   -PN : pause between events in milliseconds\n");
            printf( "   -sN : SPI clock frequency 500,000 through 32,000,000\n");
            printf( "   -t  : trim events to correct size\n");
            printf( "   -w  : disable writing to file\n");
            printf( "   -dT : data directory\n");
            printf( "   -xN : number of extra words in the event\n");
        }
    }
    printf("Recording %i files with %i events[%i] per file ",nFiles,nEvents,nBytes);
    if(writing_enabled) printf(" to directory %s",dirname);
    printf("\n");
    spi_open(spi_channel,spi_speed);

    for(nFiles;nFiles>0;nFiles--)
    {
        if(nEvents<1) nEvents = 1;
        if (writing_enabled)
        {
            time(&tmt);
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
        if(verbosity&1) printf("File %s, %i files to go.\n",pathname,nFiles);
        
        for(gEvN=0;gEvN<nEvents;)
        {
            if(verbosity&8) printf("record %i\n",gEvN);
            rc = spi_read(spi_channel,buf,nBytes);
            if(verbosity&8) dumpbuf(buf, rc);
            if(delay)   delay_ms(delay);
            if(trim_events) rc = trim_event(buf);
            pdata = buf + EVOFFSET;
            if(rc ==  0)  continue;
            if(rc == -1)
            {
                if(gEvN != 0)  
                {
                    printf("Run %s stopped by operator after %i events\n",filename,gEvN);
                    break;   //run stopped
                }
            }
            else gEvN++;
            if(verbosity&2) printf("Event %i[%i]\n",gEvN,rc);
            if(verbosity&4) dumpbuf(pdata, rc);
            if(ff) fwrite(pdata,1,rc,ff);
        }
        //printf("OK\n");
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
