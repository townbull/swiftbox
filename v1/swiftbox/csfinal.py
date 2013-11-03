import sys
import os
import os.path
import re
import readline
import json
from swift.common.bufferedhttp import http_connect_raw as http_connect
try:
  import swiftclient as cloud
except ImportError:
  print """OpenStack Swift python API  package are needed, download at:
         swiftclient https://github.com/openstack/python-swiftclient
"""
  sys.exit(1)
import swiftclient as cloud

readline.parse_and_bind('tab: complete')

class Global:
  authurl="http://10.245.123.72:8080/auth/v1.0/"
  conn=None
  testmode=1
  adminkey=888888

def connfailcb(msg="bye"):
  """call back for connection failed.
  """
  print msg
  sys.exit(1)

class Connection:
  def __init__(self,group, username, pwd, failcb=None):
    self.group=group
    self.user=username
    self.pwd=pwd
    self.conn=None
    self.connfailcb=failcb
 
  def get_role(self):
    try:
      res=http_connect("10.245.123.72", 8080, "GET", \
        "/auth/v2/%s/%s"%(self.group, self.user), \
        {"X-Auth-Admin-User":".super_admin", \
          "X-Auth-Admin-Key": "%s"%(Global.adminkey)}).getresponse()
      info=res.read()
      info=json.loads(info)
      for val in [ x["name"] for x in info["groups"]]:
        if val.startswith("."):
          return (0, val)
      return (0, "non-admin") 
    except Exception, e:
      return (1, None) 
 
  def connect(self):
    try:
      self.conn=cloud.Connection(\
        user="%s:%s"%(self.group, self.user), key=self.pwd, \
        authurl=Global.authurl)
      self.conn.get_auth()
      return True
    except cloud.ClientException , e:
      exctype, value=sys.exc_info()[:2]
      print "%s: %s"%(exctype.__name__, value)
      if self.connfailcb is not None:
        self.connfailcb("connection failed:")
      return False

  def list_containers(self):
    msg=[]
    try:
      for item in self.conn.get_account()[1]:
        #msg.append( "name: %s, obj count: %d, total bytes: %d"%(\
        #    item["name"], item["count"], item["bytes"]))
        if not item["name"].endswith("_segments"): #not display segment containers
          header=self.conn.head_container(item["name"])
          x={"name": None, "account": None, "count":None, "read-ACL":None,\
            "write-ACL":None,}
          x["name"]=item["name"]
          x["account"]=self.conn.url.rsplit("/", 1)[-1]
          x["count"]=item["count"]
          x["bytes"]=item["bytes"]
          x["read-ACL"]=header.get("x-container-read", " ")
          x["write-ACL"]=header.get("x-container-write", " ")
          msg.append(x)
      return (0, msg)
    except cloud.ClientException , e:
      exctype, value=sys.exc_info()[:2]
      msg.append("%s:"%exctype.__name__)
      for x in str(value).split("\n"):
        msg.append(x)
      return (1, msg)
      
  
  def list_objects(self, container):
    msg=[]
    try: 
      count = 0 
      for item in self.conn.get_container(container)[1]:
         #print "name: ", item["name"] 
         #print "    bytes: ", item["bytes"]
         #print "    content_type:  ", item["content_type"]
         #print "    hash:  ", item["hash"]
         #print "    last_modified", item["last_modified"]
         obj=item["name"]
         headers=self.conn.head_object(container, obj)
         x=item
         x["bytes"]=headers.get("content-length")
         x["manifest"]=headers.get("x-object-manifest", "")
         count += 1
         msg.append(x)
      #print "( %d objects are listed)"%count 
      return (0, msg)
    except cloud.ClientException , e:
      exctype, value=sys.exc_info()[:2]
      return (1, "%s: %s"%(exctype.__name__, value))

  def _get_object_info(self, container, name):
    """ return tuple (returncode, outmsg, errmsg)
      returncode: 0 for success, 1 for failed,
      outmsg: list of strings
      errmsg: list of strings
    """
    try:
      x=self.conn.head_object(container, name)
      return (0, '\n'.join(["    %s:    %s"%(i, x[i]) for i in x])) 
    except cloud.ClientException , e:
      exctype, value=sys.exc_info()[:2]
      return (1, "%s: %s"%(exctype.__name__, value))

  def _upload_object(self, container, obj,  name):
    try:
      size=os.path.getsize(name)
      with open(name, "rb") as f:
        self.conn.put_object(container, obj, f, content_length=size)
      return (0, "upload succeeded")
    except cloud.ClientException , e:
      exctype, value=sys.exc_info()[:2]
      return (1, "%s: %s"%(exctype.__name__, value))
  
  def _upload_segment_object(self, container, obj, name, segsize):
    size=os.path.getsize(name)
    if size <=segsize:
      msg="file size smaller than segment size: %d <= %d\n"%(size, segsize)
      r=self._upload_object(container, obj,  name)
      return (r[0], msg+r[1])
    else:
      msgout=""
      try:
        #obj=name
        if obj.startswith('./') or obj.startswith('.\\'):
          obj = obj[2:]
        if obj.startswith('/'):
          obj = obj[1:]
        objmtime=os.path.getmtime(name) #modified time of file
        fullsize=os.path.getsize(name)
        #create sements container
        segcontainer="%s_segments"%container
        try:
          self.conn.put_container(segcontainer)
        except cloud.ClientException, err:
          msg = ' '.join(str(x) for x in (err.http_status, err.http_reason))
          if err.http_response_content:
            if msg:
              msg += ': '
            msg += err.http_response_content[:60]
          msgout +='Error trying to create container %r: %s\n'%(segcontainer, msg)
          return (1, msgout)
        except Exception, err:
          raise
        #set master objects
        manifest= "%s/%s/%s/%s/"%(segcontainer, obj, objmtime, fullsize)
        self.conn.put_object(container, obj, "", content_length=0, \
          headers={\
        "x-object-meta-mtime": "%s"%objmtime,
        "x-object-manifest": manifest,
        })
        #upload segments
        segment=0
        segment_start=0
        with open(name, 'rb') as fp:
          while segment_start < fullsize:
            segment_size = segsize
            if segment_start + segsize > fullsize:
              segment_size = fullsize - segment_start
            path="%s/%s/%s/%08d"%(obj, objmtime, fullsize, segment)
            self.conn.put_object(segcontainer, path, fp, \
                content_length=segment_size)
            msgout += "upload segment: %s/%s\n"%(segcontainer, path) 
            segment += 1
            segment_start += segment_size 
        #end with
        return (0, msgout)
      except cloud.ClientException, err:
        exctype, value=sys.exc_info()[:2]
        return (1,  msgout+"%s: %s"%(exctype.__name__, value))

 
  def upload_object(self, container, obj,  fname, segsize=None):
    if not os.path.exists(fname):
      print "file %s not exists"%(fname);return
    if not os.path.isfile(fname):
      print "file %s is not a file"%(fname); return 
    ct=self._get_object_info(container, obj)
    msg=[]
    if 0 == ct[0]:
      msg.append( "object   %s/%s   already exists:"%(container, obj))
      msg.extend( ct[1].strip().split("\n"))
      return (0, msg)
    else:
      r=None
      if segsize is None: 
        r=self._upload_object(container, obj, fname)
      else: 
        r=self._upload_segment_object(container, obj, fname, segsize) 
      msg.extend( r[1].strip().split("\n"))
      return (r[0], msg)
      #print "not exists" 

  def delete_object(self, container, obj):
    #ok, for the segmented data, we will get the x-object-manifest first 
    try: 
      manifest = None
      try:
        manifest = self.conn.head_object(container, obj).get(
                    'x-object-manifest')
      except cloud.ClientException, err:
        if err.http_status != 404: #not found
          raise
      self.conn.delete_object(container, obj)
      if manifest is not None: #delete segmented data as well,but not the container
        scontainer, sprefix=manifest.split("/", 1)
        for delobj in self.conn.get_container(scontainer, prefix=sprefix)[1]:
          self.conn.delete_object(scontainer, delobj["name"])
          print "delete segment: %s/%s"%(scontainer, delobj["name"])
      return (0, "delete succeeded")
    except cloud.ClientException, err:
      if err.http_status != 404:
        raise
      print 'Object %s not found' %repr('%s/%s' % (container, obj)) 
      return (1, "Cannot delet this object")     
    #try:
    #  self.conn.delete_object(container, obj)
    #  print "delete succeeded" 
    #except (IOError, cloud.ClientException), e:
    #  exctype, value=sys.exc_info()[:2]
    #  print "%s: %s"%(exctype.__name__, value)
  
  def download_object(self, container, obj, dst):
    ct=self._get_object_info(container, obj)
    chunksize=65535
    if 0 == ct[0]: #object exists
      try:
        with open(dst, 'wb') as f:
          x=self.conn.get_object(container, obj, chunksize)[1]
          for line in x: #x is a generator
            f.write(line)
        return (0, "download succeed")
      except (IOError, cloud.ClientException), e:
        exctype, value=sys.exc_info()[:2]
        return (1, "%s: %s"%(exctype.__name__, value))
    else:
      return (1, ct[1])

def dispatch(parlist):
  if parlist[0] == "?" or parlist[0] == "help" or parlist[0]== "h": #stat the file
    help()
    return
  if parlist[0]== "use":
    if len(parlist) == 4:
      Global.conn=None
      Global.conn=Connection(parlist[1], parlist[2], parlist[3])
      if not Global.conn.connect():
        Global.conn=None
      else:
        print "login as %s:%s"%(parlist[1], parlist[2])
    else:
      print "Example: use groupA userA passwordA"
    return
  if Global.conn is None:
    print "Please login first, example: use groupA userA passwordA"
    return
  if parlist[0] == "list":
    if len(parlist) == 1:
      Global.conn.list_containers()
    elif len(parlist) == 2:
      Global.conn.list_objects(parlist[1])
    else:
      print "list [container]"
  elif parlist[0] ==  "upload":
    if len(parlist) == 3:
      Global.conn.upload_object(parlist[1], parlist[2])
    elif len(parlist) == 4:
      if re.match("^[0-9]+(B|K|M|G)$", parlist[3]) is None:
        print "segment size examples: 2K, 1M, 2B, 1G. M: Mega-bytes..."
      else:
        unit=parlist[3][-1]
        size=int(parlist[3][:-1])
        segsize=None
        if "B" == unit:
          segsize= size
        elif "K" == unit:
          segsize=size*1024
        elif "M" == unit:
          segsize= size*1024*1024
        elif "G" == unit:
          segsize= size*1024*1024*1024
        Global.conn.upload_object(parlist[1], parlist[2], segsize)
    else:
      print "Example: upload containerA objA [segmensize]"
  elif parlist[0] ==  "download":
    if len(parlist) == 4:
      Global.conn.download_object(parlist[1], parlist[2], parlist[3])
    else:
      print "Example: download containerA objA fileA"
  elif parlist[0] ==  "delete":
    if len(parlist) == 3:
      Global.conn.delete_object(parlist[1], parlist[2])
    else:
      print "Example: delete containerA objA"
  else:
    print "%s not support"%parlist[0]
 
def main():
  print "type h, help or ? for help. Ctl+d to exit."
  while 1:
    try:
      par=raw_input("\n(Ctrl+d exit; Ctrl+c interrupt)>> ")
      print
      parlist=par.strip().split()
      if parlist:
        dispatch(parlist)
    except (KeyboardInterrupt, ):
      print
      continue

def help():
  print "use group username password: use 'group:username' and 'password' to login."
  print "list [container]: list the containers for the account or the objects for a container."
  print "upload container  object srcfile [segsize]: upload local file to container"
  print "download container object dstfile: download object to local"
  print "delete container object: delete object from container" 

def test():
  Global.conn=Connection("groupX", "test1", "test1pass")
  Global.conn.connect()
  #Global.conn.list_objects("testcontainer2")
  #Global.conn.download_object("tbcontainer", "08-swift-recon.txt", "fuck")
  Global.conn.upload_object("testcontainer2", "a.mov", "batman.mov", 20*1024*1024)
  sys.exit(0)

if __name__ == "__main__":
  #test()
  try:
    if Global.testmode is not None:
      Global.conn=Connection("groupX", "test1", "test1pass")
      Global.conn.connect()
    main()
  except EOFError, e:
    print; sys.exit(1)
  except (Exception, ), e:
    import traceback
    traceback.print_exc()
