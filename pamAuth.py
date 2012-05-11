#!/usr/bin/env python2
#File: pamAuth.py
#Project: CSIS 440 Final Project - SSH Server
#Author: Dustin Ernst (Sam Sussman, Charles Belanger)
#Provides a function to authenticate a user against the system's pam setup.

import sys
import ctypes
import ctypes.util

#These are the only two c libs we'll need, libc and libpam.
libc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("c"))
libpam = ctypes.cdll.LoadLibrary(ctypes.util.find_library("pam"))

#Need to create a bunch of structure classes first
class pam_message(ctypes.Structure):
   """
   http://linux.die.net/man/3/pam_conv
   """
   _fields_ = [("msg_style", ctypes.c_int),("msg", ctypes.c_char_p)]

class pam_response(ctypes.Structure):
   """
   http://linux.die.net/man/3/pam_conv
   """
   _fields_ = [("resp", ctypes.c_char_p),("resp_retcode", ctypes.c_int)]

#Signature for our pam_conv callback function.
pam_conv_sig = ctypes.CFUNCTYPE(ctypes.c_int,\
ctypes.c_int,\
ctypes.POINTER(ctypes.POINTER(pam_message)),\
ctypes.POINTER(ctypes.POINTER(pam_response)), \
ctypes.c_void_p)
                                
class pam_conv(ctypes.Structure):
   """
   http://linux.die.net/man/3/pam_conv
   """
   _fields_ = [("conv", pam_conv_sig),
               ("appdata_ptr",ctypes.c_void_p)]

class pam_handle_t(ctypes.Structure):
   """
   http://linux.die.net/man/3/pam_start
   Is apparently a blind structure.
   We'll give it a void pointer for a field.
   This pointer will be filled in by pam_start.
   """
   _fields_ = [("pam_handle", ctypes.c_void_p)]
   def __init__(self):
      self.pam_handle = 0

#http://linux.die.net/man/3/pam_start
pam_start = libpam.pam_start
pam_start.restype = ctypes.c_int
pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(pam_conv), ctypes.POINTER(pam_handle_t)]

pam_authenticate = libpam.pam_authenticate
pam_authenticate.restype = ctypes.c_int
pam_authenticate.argtypes = [pam_handle_t, ctypes.c_int]

#Copies a string from one location in memory to another one, returns a pointer to it.
strdup = libc.strdup
strdup.restype = ctypes.POINTER(ctypes.c_char)
strdup.argstypes = [ctypes.c_char_p]

#Allocates memory for an array.
calloc = libc.calloc
calloc.restype = ctypes.c_void_p
calloc.argtypes = [ctypes.c_uint, ctypes.c_uint]

def pamAuth(username, password):
   """
   Authenticate using pam and the login service.
   Arguments are python strings of the clear-text username and password.
   Returns a bool based on the result.
   """
   @pam_conv_sig
   def conv_function(num_msg, msg, resp, appdata_ptr):
      """
      Does the "conversation" to try each message type and get the
      answer from the user.
      We'll just look for the one that doesn't echo anything and feed it
      the correct password.
      Needs to be in this scope to get the password, as we can't change
      the function signature.
      """
      #Address of a block of memory we're going to allocate for our response structs
      resparr = calloc(num_msg, ctypes.sizeof(resp))
      #Point resp at this memory
      resp[0]= ctypes.cast(resparr, ctypes.POINTER(pam_response))
      #Look for the message style that does not echo a prompt and requests
      #just a password back. This is msg_style 1 according to the libpam headers.
      for i in range(num_msg):
         if msg[i][0].msg_style == 1:
            pswd = strdup(str(password))
            resp[i].contents.resp = ctypes.cast(pswd, ctypes.c_char_p)
            resp[i].contents.resp_retcode = 0
      return 0
   #A handle for the blink structure pam_start fills in
   pamh = pam_handle_t()
   conv = pam_conv(conv_function, 0)
   #Setup pam, get the response to the message we want.
   #"login" is just the most basic pam auth stack. Could create a new
   #file in /etc/pam.d and use the name of that instead of we wanted to.
   pam_start("login", username, ctypes.pointer(conv),ctypes.pointer(pamh))
   #Ask pam if that response results in a valid login.
   res = pam_authenticate(pamh, 0)
   #Turn that result into a bool to return.
   return res == 0

#just a quick test to be sure it works
#not the right user/pass, but you could put them in to test...
if __name__ == "__main__":
   print repr(pamAuth("ernstdu", "cats"))