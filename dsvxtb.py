# -*- coding: utf-8 -*-

#GUI for DSVXTB
#version:       4
#author:        Andrey Sukhanov
#modified:      08/16/2013

#version:	5
#modified:	09/10/2013
# External trigger and DAQ interface controls.
# SVX4 downloading file changed from fem.fem to SVX_config.txt
# Changing between Internal and External trigger will automatically re-load the sequencer 
# using correspondig files: sqn_trig_internal.txt or sqn_trig_external.txt
# Diring Load Sequencer operation the verbosity dropped to avoid lengthy OKs.
#

#version:	6
#modified:	09/11/2013
# The output data file (when RS232 mode is selected) is changed to binary *.dq4 format
# for compatibility with the files, written in USB mode).
# Removed control of FPGA analog subsytem.

#version:	7
#modified:	10/09/2013
# Added Slave CSR configuration

#version:       8
#modified:	10/16/2013
# UART list populated.
# Version and Switches implemented and color coded. Download is color coded.
# The program analises the serial input stream for CSR status, thread.data changed to 16-slot fifo.
# Channel numbers affects the corresponding bits in CSR.

#   2013-10-22  AS
#*  v9 Start DAQ checks if sequencer was loaded

#   2013-10-29  AS
#*  v10 Checkbox Pedestal removed, Calibration added. CN color turned red when Channel Numbers released
#Per-line handshaking with DAQ is introduced for RS232 interface.
#The Record separator is changed from '$' to '\x1E'
#The DAQ is sending acknowledge '\x6' for each line
#This version works for dsvxtb-v119-105 and higher.

#  2013-10-30	AS
#* Filenames and writing progress in information window.
#version = 11

#   2013-11-01  AS
#*  Correct the setting of number of modules to read in Start DAQ
#version = 12

#   2013-11-07  AS
#*  Removed READOUT (0x28) command from the sqn_pedestals.txt, CARB-v16 does it
#automatically, 12 FEClocks after BEMODE.

#   2013-12-10  AS
#*  Replaced Slave CSR sequence with o0 command
#version = 13

#   2014-01-02  AS
#*  Multiple carrier boards
#version = 14

#   2014-01-10  AS
#*  Slave Reset
#version = 15

#   2014-01-14  AS
#*  Sequencer reset.

#   2014-02-17  AS
#*  Data directory changed to D:/data

#   2014-03-26  AS
#*  For DSVXTB-v17C and higher: 

#   2014-04-08  AS
#*  Dealing with FEM simulator 

#   2014-06-03  AS
#*  config.py

#   2014-06-06  AS
#*  FEM_ID
#version = 18

#   2014-06-16  AS
#   Added SPI support
#version 19

version = 19

import sys
#from time import sleep
from PyQt4 import QtCore, QtGui
import serial
from collections import deque
#
import thread
import datetime
import os
import time
import random
import platform
import glob
from array import array

try:
    from dsvxtb_ui import Ui_dsvxtb
except:
    print("dsvxtb_ui.pyc does not exist, to generate it use: \npyuic4 dsvxtb.ui -o dsvxtb_ui.py")
    sys.exit()

# Any dynamic configurations assumed to be in config.py
# It is not used in version 3 or above
import config
g = config.Config()
data_directory = g.data_directory
print('data directory: '+data_directory)
serial_device = g.serial_device
print('serial device: '+g.serial_device)

#^^^^^^^^ globals
# HDR_FEMId is temporary, it should be handled inside the FPGA
HDR_FEMId = 0xff
HDR_ChainMask = 1
#________

def APB_Slave(bank,offset):	#returns the register index of the DSVXTB APB slaves
	return bank*64 + offset*4

def reverseBits(original,numbits):
        return sum(1<<(numbits-1-i) for i in range(numbits) if original>>i&1)

class SleepPrint(QtCore.QThread):
        procDone = QtCore.pyqtSignal(bool)
        line = QtCore.pyqtSignal(str)
        procIter = QtCore.pyqtSignal(int)
        streaming_in_progress = 0
	# data will store last 16 lines
        data = deque()
        for ii in range(16):
            data.append('')
        sfil = None
        def run(self):
	    print('SleepPrint started')
	    while myapp.connected:
 		txt = myapp.ser.readline()
		if len(txt) == 0:
			time.sleep(0.1)
			continue
		#print('sleep: '+txt)
       		drop = self.data.popleft()
		self.data.append(txt)
		#if txt[0] == '$':      #chipskop data
		if txt[0] == '\x1E':    # Marker for data to be streamed
		    #print("streaming out \'"+txt+"\'")
		    if txt[1] == 'E':	# End of transmission
                        try:
                            elapsed_sec = time.time() - start
                        except:
                            pass
			try:
			    if not self.sfil.closed:
                                fpos = self.sfil.tell()
                                txtout = 'Closed '+self.sfil.name+'['+str(fpos)+'] after '+str(round(elapsed_sec,1))+'s'
				print(txtout)
				self.line.emit(txtout)
				self.sfil.close()
			except:
                    	    if (myapp.ui.my_DAQ_Interface.currentText() == 'RS232'):
                                print('ERROR Data for closed file:'+txt[1:])
                        continue
			# for windows
			if self.streaming_in_progress == 1:	# launch the command to plot the chipskop data
                            os.system('start /B python waveplot_logic_hex.py '+self.sfil.name)
                            #linux equivalent:
			    #os.system('python waveplot_logic_hex.py '+self.sfil.name+'&')
			elif self.streaming_in_progress == 2:
			    notification_file = open(data_directory+"daqcapture.dq0",'w')
			    notification_file.write(self.sfilname)
			    notification_file.close()
			self.streaming_in_progress = 0
			continue
		    elif self.streaming_in_progress == 0:    #check for data type
                        try: 
                            if not self.sfil.closed:
                                txtout = 'File ' + self.sfil.name + ' is not closed'
                                print(txtout)
                                self.line.emit(txtout)
                                continue
                        except:
                            pass
			if txt[2] =='C':	# chipskop data
			    self.streaming_in_progress = 1
			    self.sfil = open(datetime.datetime.today().strftime(data_directory+"wpl_%y%m%d%H%M.wpl"),'w')
			elif txt[2] =='D':
			    self.streaming_in_progress = 2
			    self.sfilname = datetime.datetime.today().strftime("%y%m%d%H%M.dq4")
			    self.sfil = open(data_directory+self.sfilname,'wb')
			if not self.sfil.closed:
                            txtout = 'Opened '+self.sfil.name
			    print(txtout)
			    self.line.emit(txtout)
			    start = time.time()
			    olddifftime = 0
		    else:
			if txt[1] == '$':	#skip the comment
			    continue
			if self.streaming_in_progress == 2:
                            #DAQ data, write them to file
			    myapp.ser.write('\6')  # send back acknowledge
			    ar = array('B')
			    #print(int(len(txt)-2)/2)
			    try:
			      for ii in range((len(txt)-2)/2):
				  ar.append(int(txt[ii*2+1:ii*2+3],16))
			    except:
			      pass
			    ar.tofile(self.sfil)
                            difftime = int((time.time() - start))
                            if difftime/10 != olddifftime/10:
                                txtout = str(difftime)+'s: bytes out: '+str(round(self.sfil.tell()/1000.,1))+'kB'
                                self.line.emit(txtout)
                            olddifftime = difftime
 			else:
			    myapp.ser.write('\6')  # send back acknowledge
			    self.sfil.write(txt[1:])
		#elif txt[0] == 'V':
		#    #print('V: '+txt.rstrip())
		#    myapp.analogFile.write(txt.rstrip()+'\n')
		#    myapp.analogFile.flush()
		else:
		    self.line.emit(txt.rstrip())
	    print('SleepPrint ended')        
        
def list_serial_ports():
    system_name = platform.system()
    if system_name == "Windows":
        # Scan for available ports.
        available = []
        for i in range(256):
            try:
                s = serial.Serial(i)
                #print('Port '+s.name)
                available.append(s.name)
                s.close()
            except serial.SerialException:
		pass
        return available
    else:
        # Assume Linux or something else
	serial_device = g.serial_device
        return glob.glob(serial_device) # + glob.glob('/dev/ttyS*')

class myControl(QtGui.QMainWindow):
    #helper functions
    def scmd(self,cmd):
	print("sending "+"\'"+str(cmd)+"\'")
	self.ser.write(str(cmd))

    def connect(self):
        self.updateTxt("host: GUI v"+str(version))
        self.ser = serial.Serial()
        #self.ser.baudrate = g.Run_COM_BaudRate
        self.ser.baudrate = int(self.ui.my_COM_BAUD.currentText())        
        # no effect #self.ser.xonxoff = True
        # no effect #self.ser.writeTimeout = 1
        
        #IMPORTANT setting for serial data taking,
        #0.01 is too small for windows7
        #0.1 is good for 460800 bod, data taking rate is 60 ev/s
        #0.5 is good for 115200 bod as well as for 460800, data taking rate is 60 ev/s
        self.ser.timeout = 0.5
        
        portsList = list_serial_ports()
        #self.ser.port = portsList[len(portsList)-1]
        #print('port: '+self.ui.my_COM.currentText())
        self.ser.port = str(self.ui.my_COM.currentText())
        try:
	    self.ser.open()
        except serial.serialutil.SerialException:
            print(("ERROR: could not open port " + self.ser.port))
            #trying to call #serial.tools.list_ports()
            #os.system("python -m serial.tools.list_ports")
            #sys.exit()
        if self.ser.isOpen():
	    self.connected = True
	    print('Serial port ' +  str(self.ser.name) + ' opened')
	    print('timeout:'+str(self.ser.timeout)+' xonxoff:'+str(self.ser.xonxoff)+' rtscts:'
                  +str(self.ser.rtscts)+' CharTimeout: '+str(self.ser.interCharTimeout)+' WTimeOut='+str(self.ser.writeTimeout))
	    self.ser.flushInput();
	    self.scmd("s")	#print status
	else:
	    print('ERROR. Could not open serial port ' + str(self.ser.port))
	    #exit()
	
    def analogOpen(self):
                self.analogFile = open('analog.log','a')
                self.analogFile.write('New\n')
        
    # GUI stuff
    def __init__(self, parent=None):
        QtGui.QWidget.__init__(self, parent)
        self.ui = Ui_dsvxtb()
        self.ui.setupUi(self)
        #
        # Class variables
        self.exiting = 0
        self.greading_stopped = True
        self.thread = SleepPrint()
        self.wtext = self.thread.data
        self.connected = False
        self.Verbosity = 0
        self.lastDACCmd = 0
        self.ramped = 0
        self.carrier_status = -1
        #self.DAQ_running = 0
	
        # Init list of serial ports
	portsList = list_serial_ports()
	print("Available ports: "+str(portsList))
	for ii in range(len(portsList)):
            self.ui.my_COM.insertItem(ii,portsList[ii])
        self.ui.my_COM.setCurrentIndex(len(portsList)-1)

        # Init the GUI items
        self.ui.my_COM_BAUD.insertItem(0,'4800')
        self.ui.my_COM_BAUD.insertItem(1,'9600')
        self.ui.my_COM_BAUD.insertItem(2,'19200')
        self.ui.my_COM_BAUD.insertItem(3,'38400')
        self.ui.my_COM_BAUD.insertItem(4,'57600')
        self.ui.my_COM_BAUD.insertItem(5,'115200')
        self.ui.my_COM_BAUD.insertItem(6,'230400')
        self.ui.my_COM_BAUD.insertItem(7,'460800')
        self.ui.my_COM_BAUD.insertItem(8,'921600')
        self.ui.my_COM_BAUD.setCurrentIndex(5)
        
        # Fill the Interface items
        self.ui.my_DAQ_Interface.insertItem(0,'RS232')
        self.ui.my_DAQ_Interface.insertItem(1,'TLINK')
        self.ui.my_DAQ_Interface.insertItem(2,'SPI')
        self.ui.my_DAQ_Interface.setCurrentIndex(0)

	# Fill trigger sources
        self.ui.my_DAQ_ExTrig.insertItem(0,'CLK')
        self.ui.my_DAQ_ExTrig.insertItem(1,'LVDS')
        self.ui.my_DAQ_ExTrig.insertItem(2,'OSC')
        self.ui.my_DAQ_ExTrig.insertItem(3,'TTL')
        self.ui.my_DAQ_ExTrig.insertItem(4,'INT')
        self.ui.my_DAQ_ExTrig.setCurrentIndex(0)

	# Fill trigger frequencies
        self.ui.my_TrigFreq.insertItem(0,'19 Hz')
        self.ui.my_TrigFreq.insertItem(1,'76 Hz')
        self.ui.my_TrigFreq.insertItem(2,'305 Hz')
        self.ui.my_TrigFreq.insertItem(3,'1.22 KHz')
        self.ui.my_TrigFreq.insertItem(4,'4.9 KHz')
        self.ui.my_TrigFreq.insertItem(5,'19.5 KHz')
        self.ui.my_TrigFreq.insertItem(6,'78 KHz')
        self.ui.my_TrigFreq.insertItem(7,'5 MHz')
        self.ui.my_DAQ_ExTrig.setCurrentIndex(0)
        
        #self.analogOpen()

        self.connect()
        if self.ser.isOpen():
                        self.ui.my_Connect.setCheckState(QtCore.Qt.Checked)
                        #self.reg_Write(2,0xF0000000)    # clear bits of pulsed command field to avoid confusion of pulsing bit which is already set
    # Connect the buttons
        QtCore.QObject.connect(self.ui.my_Run_Exit,QtCore.SIGNAL("clicked()"),self.my_Run_Exit)
        QtCore.QObject.connect(self.ui.my_Run_Status,QtCore.SIGNAL("clicked()"),self.my_Run_Status)
        QtCore.QObject.connect(self.ui.my_Run_Command,QtCore.SIGNAL("clicked()"),self.my_Run_Command)
        QtCore.QObject.connect(self.ui.my_Run_Command_Txt,QtCore.SIGNAL("returnPressed()"),self.my_Run_Command)
        QtCore.QObject.connect(self.ui.my_Run_Command_Repeat,QtCore.SIGNAL("clicked()"),self.my_Run_Command_Repeat)
        QtCore.QObject.connect(self.ui.my_Run_Command_Recording,QtCore.SIGNAL("released()"),self.my_Run_Command_Recording)
        QtCore.QObject.connect(self.ui.my_Run_EFROM,QtCore.SIGNAL("clicked()"),self.my_Run_EFROM)
        QtCore.QObject.connect(self.ui.my_Run_Reg_Read,QtCore.SIGNAL("clicked()"),self.my_Run_Reg_Read)
        QtCore.QObject.connect(self.ui.my_Run_Reg_Input,QtCore.SIGNAL("clicked()"),self.my_Run_Reg_Input)
        QtCore.QObject.connect(self.ui.my_Run_Reg_Set,QtCore.SIGNAL("clicked()"),self.my_Run_Reg_Set)
        QtCore.QObject.connect(self.ui.my_Run_Reg_Clear,QtCore.SIGNAL("clicked()"),self.my_Run_Reg_Clear)
        QtCore.QObject.connect(self.ui.my_Run_Reg_Pulse,QtCore.SIGNAL("clicked()"),self.my_Run_Reg_Pulse)
        QtCore.QObject.connect(self.ui.my_Run_Reg_Add,QtCore.SIGNAL("clicked()"),self.my_Run_Reg_Add)
        QtCore.QObject.connect(self.ui.my_Dbg_Verbosity,QtCore.SIGNAL("clicked()"),self.my_Dbg_Verbosity)
        QtCore.QObject.connect(self.ui.my_Dbg_Verbosity_Txt,QtCore.SIGNAL("returnPressed()"),self.my_Dbg_Verbosity)
        QtCore.QObject.connect(self.ui.my_Run_Stop,QtCore.SIGNAL("clicked()"),self.my_Run_Stop)
        QtCore.QObject.connect(self.ui.my_Run_Delay,QtCore.SIGNAL("clicked()"),self.my_Run_Delay)
        QtCore.QObject.connect(self.ui.my_Run_Chipskop,QtCore.SIGNAL("clicked()"),self.my_Run_Chipskop)
        QtCore.QObject.connect(self.ui.my_Run_Chipskop_Arm,QtCore.SIGNAL("clicked()"),self.my_Run_Chipskop_Arm)
        QtCore.QObject.connect(self.ui.my_Run_Chipskop_Trig,QtCore.SIGNAL("clicked()"),self.my_Run_Chipskop_Trig)
        QtCore.QObject.connect(self.ui.my_Connect,QtCore.SIGNAL("released()"),self.my_Connect)
        QtCore.QObject.connect(self.ui.my_CTest,QtCore.SIGNAL("clicked()"),self.my_CTest)
        QtCore.QObject.connect(self.ui.my_STest,QtCore.SIGNAL("clicked()"),self.my_STest)
        QtCore.QObject.connect(self.ui.my_Download,QtCore.SIGNAL("clicked()"),self.my_Download)
        QtCore.QObject.connect(self.ui.my_DAQ_Start,QtCore.SIGNAL("clicked()"),self.my_DAQ_Start)
        QtCore.QObject.connect(self.ui.my_DAQ_Stop,QtCore.SIGNAL("clicked()"),self.my_DAQ_Stop)
        QtCore.QObject.connect(self.ui.my_Reset,QtCore.SIGNAL("clicked()"),self.my_Reset)
        QtCore.QObject.connect(self.ui.my_Help,QtCore.SIGNAL("clicked()"),self.my_Help)
        QtCore.QObject.connect(self.ui.my_Load_Sequencer,QtCore.SIGNAL("clicked()"),self.my_Load_Sequencer)
#        QtCore.QObject.connect(self.ui.my_DAQ_ExTrig,QtCore.SIGNAL("released()"),self.my_DAQ_ExTrig)
        QtCore.QObject.connect(self.ui.my_DAQ_ExTrig,QtCore.SIGNAL("activated(QString)"),self.my_DAQ_ExTrig)
        QtCore.QObject.connect(self.ui.my_Calibration,QtCore.SIGNAL("released()"),self.my_Calibration)
        QtCore.QObject.connect(self.ui.my_Channel_Numbers,QtCore.SIGNAL("released()"),self.my_Channel_Numbers)
        QtCore.QObject.connect(self.ui.my_DAQ_Interface,QtCore.SIGNAL("activated(QString)"),self.my_DAQ_Interface)
        QtCore.QObject.connect(self.ui.my_Slave_CSR,QtCore.SIGNAL("clicked()"),self.my_Slave_CSR)
        QtCore.QObject.connect(self.ui.my_TrigFreq,QtCore.SIGNAL("activated(QString)"),self.my_TrigFreq)
        QtCore.QObject.connect(self.ui.my_Old_CARB,QtCore.SIGNAL("released()"),self.my_Old_CARB)
        QtCore.QObject.connect(self.ui.my_CARB_Sim,QtCore.SIGNAL("released()"),self.my_CARB_Sim)
        
        # Start threads
        #thread.start_new_threAAad(threadFeedBack,("FB",""))
        self.thread.line.connect(self.updateTxt)
        #self.thread.procDone.connect(self.fin)
        #self.thread.procIter.connect(self.changeWindowTitle)
        self.thread.start()
        
    # Slots
    def my_Run_Exit(self):
        # safe exiting
        self.exiting = 1
        sys.exit(app.exec_())
        
    def my_Run_Status(self):
        self.scmd("s")
        
    def my_Run_Command(self):
        line = self.ui.my_Run_Command_Txt.text()
        line += ' ' #to easy split
        words = line.split(' ')
        try:
            i = int(str(words[1]),0)
            words[1] = str(i)
        except:
            pass
        line = words[0] + ' ' + words[1] + ' ' #client needs separator at the end
        self.scmd(str(line)) 
        
    def my_Run_Command_Repeat(self):
	ntimes = self.ui.my_Run_Command_Repeat_NTimes.text()
	line = "p"+ntimes+' '
	self.scmd(str(line))
                
    def my_Run_Command_Recording(self):
        if self.ui.my_Run_Command_Recording.checkState():
            self.ui.my_Run_Command_Repeat.setEnabled(False)
            self.scmd("[")
        else:
            self.ui.my_Run_Command_Repeat.setEnabled(True)
            self.scmd("]")
            
    def my_Run_EFROM(self):
	self.scmd("e")
                
    def my_Run_Reg_Reader(self,reg):
	line = "r"+str(int(self.ui.my_Run_Reg.text())+reg)+' '
	self.scmd(line)
                
    def my_Run_Reg_Read(self):
        self.my_Run_Reg_Reader(0)
                
    def my_Run_Reg_Input(self):
        self.my_Run_Reg_Reader(1)
                
    def reg_Write(self, reg, val):
        line = "w"+str(reg)+' '+str(val)+' '
        self.scmd(line)
                
    def my_Run_Reg_Writer(self,reg):
        reg = int(self.ui.my_Run_Reg.text())+reg
        val = int(str(self.ui.my_Run_Reg_Value.text()),0)
        self.reg_Write(reg,val)
                
    def my_Run_Reg_Write(self):
        self.my_Run_Reg_Writer(0) # avoid using it, use bit sets and bit clears instead 
                
    def my_Run_Reg_Set(self):
        self.my_Run_Reg_Writer(1)
                
    def my_Run_Reg_Clear(self):
        self.my_Run_Reg_Writer(2)
                
    def my_Run_Reg_Pulse(self):
        self.my_Run_Reg_Writer(0)
                
    def my_Run_Reg_Add(self):
	reg = self.ui.my_Run_Reg.text()
	val = int(str(self.ui.my_Run_Reg_Value.text()),0)
	line = "a"+reg+' '+str(val)+' '
	self.scmd(line)
                
    def my_Dbg_Verbosity(self):
	self.Verbosity = int(str(self.ui.my_Dbg_Verbosity_Txt.text()),0)
	line = "l"+str(self.Verbosity)+' '
	self.scmd(line)
                
    def my_Run_Stop(self):
        self.scmd("xx")# double x will stop repeating process
                
    def my_Run_Delay(self):
	reg = int(float(str(self.ui.my_Run_Delay_Txt.text()))*1000.)
	line = "d"+str(reg)+' '
	self.scmd(line)
                
    def my_Run_Chipskop_Arm(self):
        self.reg_Write(0,0x20000000)  # pulse bit mask
        self.ui.my_Run_Chipskop.setEnabled(True)
        
    def my_Run_Chipskop_Trig(self):
        self.reg_Write(2,0x00000E00)    # clear chipskop selection bits
        self.reg_Write(0,0x00000200)   # pulse bit mask
                
    def my_Run_Chipskop(self):
        #if self.DAQ_running:
        #    self.updateTxt('host: DAQ should be stopped')
        #    return
        self.scmd('c')
        self.ui.my_Run_Chipskop.setEnabled(False)
                              
    def my_Connect(self):
	if self.ui.my_Connect.checkState():
	    self.connect()
	    if self.ser.isOpen():
			self.thread.start()
	else:
	    self.connected = False
	    self.ser.close()
	    print('serial connection closed')
                        
    def updateTxt(self,txtt):
        self.ui.my_Run_OutputWindow.append(txtt)

    def my_CTest(self):
	self.scmd('t0 0')
	
    def my_STest(self):
	self.scmd('t0 1')
	
    def my_Download(self):
	dwnl_file = open('SVX_config.txt','r')
	txt = 'Opened '+dwnl_file.name
        self.updateTxt(txt)
        string = '0b'
        for line in dwnl_file:
	    if line[0] != '#':
		#print(line)
		string += line
	ostr = string.translate(None,' \r\n') #concatenate all strings
	num = int(ostr,2)
	ostr = hex(num)
	ostr = ostr[2:]
	ostr = ostr.translate(None,'L') #remove trailing 'L'
	ostr = ostr.rjust(48,'0') #recover leading zeroes
	#if len(ostr) != 48:
	#    print("ERROR, Length of the configuration string != 192.")
	#    print('['+str(len(ostr))+"]: \'"+ostr+"\'")
	#    return -1
	nSVX = str(self.ui.my_NSVX4.text())
	ostr = 'o'+nSVX+' '+ostr+' ' #extra space at the end is necessary
        self.scmd(ostr)
	dwnl_file.close()
	time.sleep(0.5)  # wait until last message from board was received
	#print('Response: '+self.wtext[len(self.wtext)-1]+'|')
	
	lastline = self.wtext[len(self.wtext)-1]
	if  lastline[:2] == 'OK' or lastline[:3] == 'Cal': #CalStrobe sent\r\n':
            self.ui.my_Download.setStyleSheet("QPushButton { background-color : rgb(128,255,128); color : black; }")
            txtx='Download OK'
        else:
            self.ui.my_Download.setStyleSheet("QPushButton { background-color : rgb(255,100,100); color : black; }")
            txtx='Download FAILED'
        self.updateTxt('host: '+txtx)
	print(txtx)

    def my_check_sequenser(self):
        # check if sequenser was loaded
	self.SeqReset()
	self.scmd('r320 2 ')    #read first word
	time.sleep(0.1)
	val = 0
	nn = 1
	if self.wtext[len(self.wtext)-1][:2] == 'OK':
            nn = 2
	try:
            val = int(self.wtext[len(self.wtext)-nn].split()[2],0)
        except:
            pass
        #print('val='+str(val))
        
	if val == 0:
            print('Sequencer not loaded, loading it.')
            # self.ui.my_Load_Sequencer.setStyleSheet("QPushButton { background-color : rgb(255,100,100); color : black; }")
            # it is enough to turn it red
            self.my_Load_Sequencer()
            return 0
        else:
            return 1
        
    def my_DAQ_Start(self):
        
	self.my_check_sequenser()
	self.ui.my_DAQ_ExTrig.setEnabled(False)
	#self.ui.my_Channel_Numbers.setEnabled(False)
	self.ui.my_DAQ_Interface.setEnabled(False)
	self.ui.my_Download.setEnabled(False)
	#self.ui.my_Load_Sequencer.setEnabled(False)
	#TODO: This will un-arm the sequencer# self.MasterReset()	# to reset event number
	ostr = "q"
	ostr += str(int(float(str(self.ui.my_DAQ_NEvents.text()))))
	mode = 0
	#if self.ui.my_Retrigger.checkState():
	#    mode |= 1
	#if self.ui.my_DAQ_Simulate.checkState():
	#    print("Data will be simulated!")
	#    mode |= 2
	if (self.ui.my_DAQ_Interface.currentText() == 'TLINK'):
	    mode |= 4
        if (self.ui.my_DAQ_Interface.currentText() == 'SPI'):
            mode |= 4   #same setting as with TLINK
	if self.ui.my_Channel_Numbers.checkState():
	    mode |= 8
	src = self.ui.my_DAQ_ExTrig.currentIndex()
	if src == 4:
            src = 3
	print('trigSource='+str(src))
	mode |= (src&0x3)<<4

	# set the number of modules to read
	HDR_NChips = int(self.ui.my_NSVX4.text())
	print('DAQ will read '+str(HDR_NChips)+' SVX4s')
	self.reg_Write(APB_Slave(1,0),((HDR_ChainMask & 0xf) | (HDR_NChips & 0xff)<<4))
	self.reg_Write(APB_Slave(1,3),(HDR_FEMId & 0x3f))
	#
	ostr += " " + str(mode) + " "
        #self.DAQ_running = 1
        self.scmd(ostr)
        
    def my_DAQ_Stop(self):
        self.ui.my_DAQ_ExTrig.setEnabled(True)
        self.ui.my_Channel_Numbers.setEnabled(True)
        self.ui.my_DAQ_Interface.setEnabled(True)
        self.ui.my_Download.setEnabled(True)
        self.ui.my_Load_Sequencer.setEnabled(True)
        self.reg_Write(2,0x04000000) #clear TLINK/SPI enable bit. (Logically it is better be done inside firmware.)
        mode = 0x8000
        ostr = "q0 " + str(mode) + " "
#self.DAQ_running = 0
        self.scmd(ostr)
        
    def MasterReset(self):
        self.scmd('w0 0x10000000 ')

    def SeqReset(self):
        self.scmd('w0 0x70000000 ')
        
    def my_Reset(self):
        self.MasterReset()
	self.scmd('w0 0x60000000 ')
	
    def my_Help(self):
	self.scmd('h ')
	
    def my_Load_Sequencer(self):
	self.scmd("l3 ")	#change verbosity to minimal
	self.SeqReset()
	#if self.ui.my_DAQ_ExTrig.checkState():
	if self.ui.my_DAQ_ExTrig.currentIndex() <= 3:
	    seq_file = open('sqn_trig_external.txt','r')
	else:
	    if self.ui.my_Calibration.checkState():
	      seq_file = open('sqn_calibration.txt','r')
	    else:
	      seq_file = open('sqn_pedestals.txt','r')
        txt = 'Opened '+seq_file.name
        self.updateTxt(txt)
        for line in seq_file:
	    if line[0] == '#':
		continue
	    ostr = 'w320 '+line.split()[0]+' '
	    self.scmd(ostr)
	seq_file.close()
	self.my_Dbg_Verbosity()	# recover verbosity
        self.ui.my_Load_Sequencer.setStyleSheet("QPushButton { background-color : rgb(128,255,128); color : black; }")
	
    def my_DAQ_Interface(self):
	if (self.ui.my_DAQ_Interface.currentText() == 'TLINK'):
	    print("Data destination interface changed to TLINK")
	    self.ui.my_DAQ_NEvents.setEnabled(False)
 	    #self.ui.my_DAQ_Writing.setEnabled(False)
 	else:
	    print("Data destination interface changed to RS232")
	    self.ui.my_DAQ_NEvents.setEnabled(True)
 	    #self.ui.my_DAQ_Writing.setEnabled(True)
 	    
    def my_DAQ_ExTrig(self):
	self.my_Load_Sequencer()

    def my_Calibration(self):
	self.my_Load_Sequencer()

    def my_Channel_Numbers(self):
	self.my_Load_Sequencer()
        self.ui.my_CN.setStyleSheet("QLabel { background-color : rgb(255,100,100); color : black; }")

    def my_Slave_CSR(self):
	#self.scmd('l8 ')	#change verbosity to DETAILED, then the last line will be the content of the Slave CSRs
        txt = ""
        nCarB = int(str(self.ui.my_NCARB.text()))
        reg = [0,0,0,0]
        for ii in range(nCarB):
            if   ii == 0:
                    txtt = str(self.ui.my_SlaveCSR.text())
            elif ii == 1:
                    txtt = str(self.ui.my_SlaveCSR_2.text())
            elif ii == 2:
                    txtt = str(self.ui.my_SlaveCSR_3.text())
            elif ii == 3:
                    txtt = str(self.ui.my_SlaveCSR_4.text())
            txtt = txtt.zfill(4)
            
            # set 3-rd letter according to Channel Number setting, this is bit6 in CSR
            reg[ii] = int(str(txtt),16)
            if self.ui.my_Channel_Numbers.checkState():
                reg[ii] |= 0x40 # prepare to set bit6 in slave CSR
            else:
                reg[ii] &= ~0x40

            lst = list(txtt)
            lst[2] = hex((reg[ii]>>4)&0xf)[2]   # skip 0x and take only the digit
            #print(lst)
            txt += "".join(lst)

        print('Setting slave CSR to '+txt)
	self.ser.write('o0 '+txt+' ')  # excute the command

	time.sleep(0.1)  # wait until last message from board was received
	#line = self.wtext[14]
	line = self.wtext[len(self.wtext)-1]
	if self.wtext[len(self.wtext)-1][:2] == 'OK':
            print('load OK')
        for ii in range(5):
            if self.wtext[len(self.wtext)-1-ii][:9] == 'Read back':
                line = self.wtext[len(self.wtext)-ii]
                break
	#self.my_Dbg_Verbosity()	# recover verbosity
	#print('read back: '+ line)

	val = 0
	version = []
	switches = []
	csr = []
        carrier_status = 0
        for ii in range(nCarB):
            txtt = line[ii*4:4+ii*4]
            try:
                csr.append(int(txtt,16))
            except:
                pass
            #print('read:'+txtt+'='+hex(csr[ii]))
            version.append((csr[ii]>>8)&0xff)
            switches.append(csr[ii]&0x7f)
            #print('CSR='+str(hex(csr[ii]))+' vers:'+hex(version[ii])+' switches:'+bin(switches[ii]))
            if   ii == 0:
                labelVersion = self.ui.my_Label_Version
                labelSwitches = self.ui.my_Label_Switches
                labelCN = self.ui.my_CN
            elif ii == 1:
                labelVersion = self.ui.my_Label_Version_2
                labelSwitches = self.ui.my_Label_Switches_2
                labelCN = self.ui.my_CN_2
            elif ii == 2:
                labelVersion = self.ui.my_Label_Version_3
                labelSwitches = self.ui.my_Label_Switches_3
                labelCN = self.ui.my_CN_3
            elif ii == 3:
                labelVersion = self.ui.my_Label_Version_4
                labelSwitches = self.ui.my_Label_Switches_4
                labelCN = self.ui.my_CN_4
            labelVersion.setText(hex(version[ii]))
            readCN = (csr[ii]>>6)&1
            labelCN.setText(str(readCN))
            labelSwitches.setText(bin(switches[ii]))
            #source = self.sender()
            #print(str(source))
            txtx = ''
            if (version[ii] == 0xFF) or (version[ii] == 0):
                carrier_status |= 1
                labelVersion.setStyleSheet("QLabel { background-color : rgb(255,100,100); color : black; }")
                txtx = 'ERROR. Slave not powered or disconnected?'
            else:
                labelVersion.setStyleSheet("QLabel { background-color : rgb(128,255,128); color : black; }")
            if csr[ii]&0xff != reg[ii]&0xff:
                carrier_status |= 2
                labelSwitches.setStyleSheet("QLabel { background-color : rgb(255,100,100); color : black; }")
                txtx='ERROR. Token passing with slaves is broken, check connection and jumpers JP4'
            else:
                labelSwitches.setStyleSheet("QLabel { background-color : rgb(128,255,128); color : black; }")
            #print('CN,ChN='+str(readCN==1)+','+str(self.ui.my_Channel_Numbers.checkState()))
            if (readCN==1) == (self.ui.my_Channel_Numbers.checkState()!=0):
                labelCN.setStyleSheet("QLabel { background-color : rgb(128,255,128); color : black; }")
            else:
                carrier_status |= 4
                labelCN.setStyleSheet("QLabel { background-color : rgb(255,100,100); color : black; }")
        #if(carrier_status == 0):
        nSVX = 0
        for ii in range(nCarB):
            print('Carrier['+str(ii)+'] is '),
            if(version[ii]&1):
               print('SC1F'),
            else:
               print('CARB'),
            print(' in '),    
            #if(csr[ii]&0x80):
            if(reg[ii]&0x80):
                print('simulation mode')
                #set number of SVXs
                # load header 'ROC enabled' bits HDR.BEM0
                val = 0
                #for i1 in range(switches[ii]&0x03f):
                for i1 in range(reg[ii]&0x3f):
                    val = val<<1
                    val |= 1
                self.reg_Write(APB_Slave(1,1),val)
                #nSVX += switches[ii]&0x3F
                nSVX += reg[ii]&0x3F
            else:
                print('normal mode')
                # load header 'ROC enabled' bits HDR.BEM0
                val = (~switches[ii])&0x03f
                self.reg_Write(APB_Slave(1,1),val)
                #update number of SVXs
                nSVX += 2*bin(val).count('1')
            print('nSVX='+str(nSVX)+'\n')
        self.ui.my_NSVX4.setText(str(nSVX))

        if len(txtx) >0 :
            time.sleep(.1)
            print(txtx)
            self.updateTxt('host: '+txtx) #this will appear before the printout of 'r64 '
    def my_TrigFreq(self):
	src = self.ui.my_TrigFreq.currentIndex()
	print('TrigFreq='+str(src))
	self.reg_Write(384,src)
    def my_Old_CARB(self):
	if self.ui.my_Old_CARB.checkState():
            self.reg_Write(1,0x2000)    # set bit
	else:
            self.reg_Write(2,0x2000)    # clear bit
    def my_CARB_Sim(self):
	if self.ui.my_CARB_Sim.checkState():
            self.reg_Write(72,int(str(self.ui.my_SlaveCSR.text()),16))
	else:
            self.reg_Write(72,0)

   #Other methods
    def isExiting(self):
        return self.exiting
        
    def reading_stopped(self):
                return self.greading_stopped
    
if __name__ == "__main__":
    print('Running dsvxtb.py as application.')
    #print 'sys.argv['+str(len(sys.argv))+']='+sys.argv[0]
    #if len(sys.argv)>1:
        #        myCOMPort = sys.argv[1]
        #        print 'port='+myCOMPort
    app = QtGui.QApplication(sys.argv)
    myapp = myControl()
    myapp.show()
    sys.exit(app.exec_())
