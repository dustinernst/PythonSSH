#!/usr/bin/env python
# Foundations of Python Network Programming - Chapter 16 - ssh_simple.py
# Using SSH like Telnet: connecting and running two commands
import fcntl, struct
import paramiko
import sys
import os
import time
import termios
import argparse, getpass, signal
from threading import Thread
from Queue import Queue,Empty

'''
definition of a cmd with help for sftp
'''
class cmd:
  def __init__(self,help,call):
    self.help = help
    self.call = call

'''
cmds for sftp
'''
sftpcmds = {
	    "get": cmd("get remote_source local_dest",lambda client, opts: client.get(opts[0],opts[1])),
	    "put": cmd("put remote_source, local_dest" ,lambda client, opts: client.put(opts[0],opts[1])),
	    "help": cmd("help [cmd]",lambda client, opts: write((sftpcmds[opts[0]].help if len(opts) > 0 else str([x for x in sftpcmds.keys()])),True)),
	    "exit": cmd("exit",lambda client, opts: write("exit")),
	    "ls": cmd("ls [path]", lambda client, opts: write(str(client.listdir(opts[0] if len(opts) > 0 else '.')),True)),
	    "cd": cmd("cd path", lambda client, opts: client.chdir(opts[0])),
	    "cwd" : cmd("cwd -> remote current working directory", lambda client, opts: write(str(client.getcwd()),True)),
	    "lcwd" : cmd("lcwd -> local current working directory",lambda client, opts: write(os.getcwd(),True)),
	    "lls" : cmd("lls [path] -> local directory list", lambda client, opts: write(str(os.listdir(opts[0] if len(opts) > 0 else '.')),True)),
	    "lcd" : cmd("lcd path -> local change directory", lambda client, opts: os.chdir(opts[0] if len(opts) > 0 else '.')),
	    "bye" : cmd("bye", lambda client,opts: write('quit')),
	    "quit" : cmd("quit -> exits application, does not return to ssh channel", lambda client,opts: sftpcmds["exit"].call(client,opts)),
	    "rm" : cmd("rm path", lambda client, opts: client.remove(opts[0])),
	    "rmdir" : cmd("rmdir path", lambda client, opts: client.rmdir(opts[0])),
	    "lrm" : cmd("rm path", lambda client, opts: os.remove(opts[0])),
	    "lrmdir" : cmd("rmdir path", lambda client, opts: os.rmdir(opts[0])),
	    "?": cmd("?", lambda client,opts: sftpcmds["help"].call(client,opts)),
	    "rename" : cmd("remname oldpath newpath", lambda client,opts: client.rename(opts[0],opts[1])),
	    "symlink" : cmd("symlink oldpath newpath", lambda client,opts: client.symlink(opts[0],opts[1])),
	    "mkdir" : cmd("mkdir path [mode]", lambda client, opts: client.mkdir(opts[0], int(opts[1]) if len(opts) > 1 else 511))
	    }


'''
 Runs and handles an ssh connection
'''
class sshClient(paramiko.SSHClient):
   '''
      Is the program loop, creates a connection then runs until it dies.
   '''
   def __init__(self,host,user,password,port,sftp,sftp_off):
      super(sshClient,self).__init__()
      self.running = True #run the character grabbing thread when true
      try:
         self._defaultattrs = self.makeInputRaw() #no echo, buffer, or signals from terminal
         self.set_missing_host_key_policy(paramiko.AutoAddPolicy()) 
         self.connect(host, username=user, password=password,port=port) #try to connect
         channel =self.invoke_shell() #get a shell
         def handle(*args): #handle terminal resize
	   (height,width) = self.getWindowSize()
	   channel.resize_pty(width,height)
	 signal.signal(signal.SIGWINCH, handle)
	 handle(None) #set the window size currently

         self.inq = Queue() #character reading queue
         tI = Thread(target=self.ioThreadFunc, args=(sys.stdin, self.inq)) #start a thread that reads characters one by one off the stdin file
         tI.daemon = True
         tI.start()

	 while not channel.exit_status_ready():
	  #time.sleep(.001) #don't loop too fast!
	  try:
	      if not sftp: #don't read if we are entering sftp mode
		fromUser = self.inq.get_nowait() #take the next char off the queue
	  except Empty: pass
	  else: #queue is not empty
	      if (sftp or  ord(fromUser) == 1) and not sftp_off: #if C-a is hit or the sftp flag is on
		sftp = False
		self.running = False #make the read buffer stop reading
		sys.stdout.flush()
		write('Opening sftp channel...',True)
		self.restoreInput() #turn back on echo, buffering, and signals
		SFTPChannel = self.open_sftp() #open a sftp channel
		if sftpHandle(SFTPChannel).run(self.inq): #go into sftp (true is quit, exit program, false is exit, return to ssh)
		  SFTPChannel.close() #quit
		  break
		SFTPChannel.close() 
		self._defaultattrs = self.makeInputRaw() #go back to raw mode
		self.running  = True
		self.inq.queue.clear()#clear the queue
		channel.send("\n")
	      else:
		channel.send(fromUser) #send the user input to the server
	  d=self.read_until(channel)
	  if(d): #if the server had data, print it
	    write(d)
      except Exception as e:
	write( "error: " + str(e),True)
	
   '''
    Returns the size of the terminal
   '''
   def getWindowSize(self):
     return struct.unpack("HH",fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, struct.pack("HH", 0, 0)))
   
   '''
   makes the terminal input raw, no echo, buffering, or singals
   '''
   def makeInputRaw(self):
      #Get the file descriptor for standard in
      fd = sys.stdin.fileno()
      #Get the attributes belonging to the tty
      attrs = termios.tcgetattr(fd)
      oldattrs = attrs[::]
      #attrs[3] are the local modes - things like case, flush, and echo
      #& is bitwise AND operation, ~ is complement
      #termios.ECHO says to either echo or not echo a kteystroke, we don't want to
      attrs[3] = attrs[3] & ~termios.ECHO
      #termios.ICANON controls "canonical mode", which causes input to be buffered
      #by the terminal until something like EOL or EOF, we don't want that either.
      attrs[3] = attrs[3] & ~termios.ICANON
      attrs[3] = attrs[3] & ~termios.ISIG
      #Now we'll set tell the terminal to use the updated atttribute settings
      #termios.TCSANOW says to do it immediately, rather than waiting for the
      #current contents of the buffer to be handled.
      termios.tcsetattr(fd, termios.TCSANOW, attrs)
      return oldattrs 
      
   '''
    Return terminal settings to default
   '''
   def restoreInput(self):
      fd = sys.stdin.fileno()
      termios.tcsetattr(fd, termios.TCSANOW, self._defaultattrs)

   '''
   catch every character
   '''
   def ioThreadFunc(self, fd, q):
      while 1:
	if self.running:
	  q.put(fd.read(1))
   
   '''
   read everything off of the network buffer
   '''
   def read_until(self, connect):
      data = ''
      while connect.recv_ready():
         data += connect.recv(4096)
      return data
   
   '''
   Make sure the connection is closed on delete
   '''
   def __del__(self):
      self.close()
  
class sftpHandle():
   '''
    program loop for sftp mode, closes on exit
   '''
   def __init__(self,sftp):
      self.sftp = sftp
      
   def run(self,inq):
      linep=['']
      try:
	sftpcmds["cd"].call(self.sftp,['.']) #we need to do a cd to the cwd do that paramiko knows where we are and can provide cwd 
	sys.stdout.flush()
	#if cmd is empty or not exit, bye, or quit
	while len(linep) == 0 or (len(linep) > 0 and (not (linep[0] == "exit" or linep[0] == "bye" or linep[0] == "quit" ))) :
	  #if the line was not empty
	  if len(linep) > 0 and linep[0] != "":
	    try:
	      self.callSftpMethod(self.sftp,linep[0],linep[1:] if len(linep) > 1 else []) #try to call whatever cmd was provided
	    except Exception as e:
	      write(str(e),True)
	  write("sftp "+str(self.sftp.getcwd())+">")#print prompt
	  line = sys.stdin.readline() #read the line
	  l = ''
	  try:
	    l = inq.get_nowait()#check if anything exists on the queue from ssh, should only happen the first time
	  except Empty: pass
	  linep = (l+line).strip('\n').split(' ') #remove new lines and split on spaces
      except Exception as e:
	write(e,True)
      write("Closing sftp channel...",True)
      return linep[0] == "quit" #if quit we will exit the program
   '''
   calls a sftp method from the sftpcmds dict
   '''
   def callSftpMethod(self,client,method,opts):
      try:
	if (not method == None) and method in sftpcmds:#if in cmds
	  sftpcmds[method].call(client,opts)
	else: #if not print help
	  write("Command does not exist",True)
	  sftpcmds["help"].call(client,[])#print help
      except IndexError as e:
	write("incorrect parameter count: " + sftpcmds[method].help,True)

def write(message,line=False):
  sys.stdout.write(message + ('\n' * line))
  sys.stdout.flush()

def notNull(arg,default=None):
  return arg if arg != None else default

if __name__ == "__main__":
    #argument definitions
    parser = argparse.ArgumentParser(description='SSH Client')
    parser.add_argument('-o', metavar='host', type=str,
		      help='host machine')
    parser.add_argument('--sftp', dest='sftp', action='store_true', help='start in sftp mode, does nothing if --stfp_off is present')
    parser.add_argument('-u', metavar='user', type=str )
    parser.add_argument('-p', metavar='password', type=str)
    parser.add_argument('-t', metavar='port', type=int, default=22)
    parser.add_argument('--sftp_off',  action='store_true', help='disable toggle to sftp mode, default on. When off, C-a is freeded and passes through ssh')

    args = parser.parse_args()
    host = notNull(args.o)
    user = notNull(args.u,os.environ['USER'])#take user env variable from user if not provided
    password = notNull(args.p)
    port = notNull(args.t)
    if not host:
      host  = str(raw_input("Host: "))
    if not user:
      user = str(raw_input("User Name: "))
    if not password:
      password = getpass.getpass('Password: ')
    if args.sftp_off:
      print "sftp: OFF, remove --sftp_off from parameters to allow sftp mode toggle on C-a"
    c = sshClient(host,user,password,port,args.sftp,args.sftp_off)
    c.restoreInput() #make sure input is normal again
