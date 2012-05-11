#!/usr/bin/env python
import socket
import sys
import os
#Make sure you're using the modified paramiko!
import paramiko
import threading
from threading import Thread
from Queue import Queue,Empty
from pamAuth import pamAuth
import time

'''
Server settings:
PORT - Integar port value to bind to
LOCALSSHKEY - Private rsa key filename
INTERFACE - Hostname to bind to
'''
PORT = 2200
LOCALSSHKEY = '/etc/ssh/ssh_host_rsa_key'
INTERFACE = ''

class ServerClass (paramiko.ServerInterface):
   '''
   Defines how we interact with our server.
   Largely pulled from the paramiko example one, but most
   of the methods were changed significantly to make them really work.
   '''
   def __init__(self):
      #Signal we're alive
      self.event = threading.Event()
      pass

   def check_channel_request(self, kind, chanid):
      '''
      See what kind of seesion the user wants.
      We only provide for "session" right now.
      '''
      if kind == 'session':
         return paramiko.OPEN_SUCCEEDED
      return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

   def check_auth_password(self, username, password):
      '''
      Check the user's name an password against PAM.
      This is plain password auth, not interactive.
      '''
      if (pamAuth(username, password)):
         return paramiko.AUTH_SUCCESSFUL
      return paramiko.AUTH_FAILED

   def get_allowed_auths(self, username):
      '''
      Define the auth types our server supports.
      Only password at present.
      '''
      return 'password'

   def check_channel_shell_request(self, channel):
      '''
      See if they've requested a channel.
      '''
      self.event.set()
      return True

   def check_channel_pty_request(self, channel, term, width, height, pixelwidth,
                                 pixelheight, modes):
      '''
      This is supposed to create a PTY for the user, we just tell them we will.
      Simplies the logic a little for farther down.
      Can get away with this as we assume any channel they want is a shell session.
      '''
      return True

   def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
      '''
      Presently lying to the client that we've accepted their request to change their PTY.
      Can actually implement this by sending the proper control characters to their PTY process later.
      '''
      return True

class TransportClass:
   '''
   Managers our entire session from auth to requests to channels.
   '''
   def __init__(self,sock):
      #setup the transport with the client socket
      self.trans = paramiko.Transport(sock)
      #basic values for encryption
      self.trans.load_server_moduli()  
      self.trans.add_server_key(paramiko.RSAKey(filename=LOCALSSHKEY))
      #Instantiate and start our server instance for this user.
      #Think of it like a twisted protocol instance.
      self.serv = ServerClass()
      try:
         self.trans.start_server(server=self.serv)
      except Exception, e:
         print str(e)
         sys.exit("Could not start server.")

      #Accept a single channel request. We can put this in a loop later
      #to support more types than a single shell session.
      self.chan = self.trans.accept(20)
      if self.chan is None:
         self.trans.close()
         sys.exit(1)
      #Create an instance of our shell channel class that actually works
      #with the channel and creates the server-side PTY and shell for the client.
      ShellChannelClass(self)
     
class ShellChannelClass:
   '''
   Creates a PTY and shell for the user, handles i/o, and cleans up after disconnect.
   '''
   def __init__(self,t):
      #Fork a child process that has a pty associated with it.
      #pid works as normal for fork, fd is a file descriptor you can open for a
      #pipe to the stdin and stdout of the new process.
      (pid, fd) = os.forkpty()
      if pid == 0:
         #In here is the child process, we want to exec a login process over
         #python, using the client's hostname and username.
         #/bin/login will tell the system the client is logged in from the host
         #and then exec their login shell over itself. Env stuff is setup in
         #there somewhere too.
         os.execv("/bin/login",["-login","-h",str(t.trans.getpeername()[0]),"-f",str(t.trans.get_username())])
         #I don't think this line can ever actually be reached. The above one
         #might somehow throw an exception if it does fail. Think you need to
         #run out of PIDs for that to happen though, so I never tested it.
         sys.exit("Failed to execute login shell!")

      #Open pipes to the slave process.
      self.masterr = os.fdopen(fd, "rb")
      self.masterw = os.fdopen(fd, "wb")

      #Below this we create two threads, one for reading from the slave,
      #one for writing to the slave.
      #As these calls block (and there is simple way around that) we let need
      #to use threads and then drop the results we get into a thread-safe queue
      #that we can make non-blocking calls to.
      try:
         inq = Queue()
         tI = Thread(target=self.ioThreadFunc, args=(self.masterr, inq))
         tI.daemon = True
         tI.start()
      except Exception, e:
         print e
         time.sleep(1)
         sys.exit("Fatal Error: Could not start input thread.")

         
      try:
         outq = Queue()
         tO = Thread(target=self.ioThreadFunc, args=(self.chan.makefile(), outq))
         tO.daemon = True
         tO.start()
      except Exception, e:
         print e
         time.sleep(1)
         sys.exit("Fatal Error: Could not start output thread.")

      
      #While we can, loop over the input and output and read/write
      #from/to the channel.
      while tO.isAlive() and tI.isAlive():
         try:
            fromShell = inq.get_nowait()
            self.chan.send(fromShell)
         except:
            pass
         try:
            toShell = outq.get_nowait()
            self.masterw.write(toShell)
            self.masterw.flush()
         except:
            pass

      #Everything below this point is just for cleanup. Most of it
      #is only used in cases where we've died in messy fashion.
      try:
         self.masterr.close()
      except Exception, e:
         pass      
      
         
      try:
         chan.send("\r\n")
         time.sleep(1)
         chan.close()
      except Exception:
         pass

         
      try:
         self.masterw.close()
      except Exception, e:
         pass
      print "at end of client"
            
   def ioThreadFunc(self, fd, q):
      '''
      Function to making blocking reads from a fd and put values in a queue.
      Used in our i/o threads.
      '''
      while fd and q:
         try:
            q.put(fd.read(1))
         except Exception, e:
            break

         
if __name__=="__main__":
   ###Daemonizing below.
   #Change file creation mask to 777
   os.umask(0)
   #Redirect i/o from our terminals stdin/stdout
   sys.stdin = open("/dev/null","rb")  
   sys.stdout = sys.stderr = open("/dev/null","wb")
   #Fork and exit our parent process.
   if os.fork():
      sys.exit(0)
   #Give our process a new session id/process group.
   os.setsid()
   #Switch to the root dir, which we always know exists
   os.chdir("/")
   #Bind to a listening socket
   s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
   s.bind((INTERFACE, PORT))
   s.listen(100)
   #Loop over connection requests.
   #Fork for each.
   #Parent process never leaves this loop.
   while True:
      sock, addr = s.accept()
      if os.fork():
         sock.close()
         continue
      break

   ##Child process below here.
   #Close the listening socket in the cilent
   s.close()
   os.umask(0)
   #Fork again to fully remove our client from the controlling
   #daemon's process. Get it a new sid too.
   if os.fork():
      exit(0)
   os.setsid()

   #Create a transport with the client process and let that do the
   #rest of the work.
   t = TransportClass(sock)
