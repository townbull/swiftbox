# -*- coding: utf-8 -*-
from __future__ import with_statement
import os.path
import os
import re
from sqlite3 import dbapi2 as sqlite3
from flask import Flask, request, session, g, redirect, url_for, abort, \
     render_template, flash, _app_ctx_stack, send_from_directory, send_file
import csfinal as client
from werkzeug import secure_filename, SharedDataMiddleware

# configuration
SECRET_KEY = 'sfbd\x97\x1c\xbd\xdd6\xa3\x01\xff\xb5\xd1e\x92)\x9a?\xefV\\\x0b%'

class Global:
  swiftconn=None
  downloaddir="./downloads" #"/opt/www/downloads"
  uploaddir="./uploads" #"/opt/www/uploads"
 
  @staticmethod
  def setsession(conn):
    Global.swiftconn=conn
    session["logged_in"]=True
  
  @staticmethod
  def unsetsession():
    session.pop("logged_in", None)
    Global.swiftconn=None

  @staticmethod
  def isloggedin():
    if session.get("logged_in", None) is not None and Global.swiftconn is not None:
      return True
    else:
      Global.unsetsession()
      return False

# create our little application :)
app = Flask(os.path.basename(__file__))
app.config.from_object(__name__)
app.config.from_envvar('FLASKR_SETTINGS', silent=True)
app.config["MAX_CONTENT_LENGTH"] = 1*1024 * 1024 * 1024 #1GB allowd
app.wsgi_app=SharedDataMiddleware(app.wsgi_app, {
  '/plupload':os.path.dirname(__file__)+"/plupload",})
#make sure it pop session out

@app.route("/upload/<container>/", methods=["POST", "GET"])
def upload(container):
  msg=[]
  if container == "backdoor":
    return render_template("upload.html")
    
  if Global.isloggedin():
    if request.method == "POST":
      segsize=request.form["segsize"].strip()
      if segsize and not re.match("^[0-9]+(B|K|M)$", segsize):
        flash("segsize format example: 1B, 1K, 1M.... B:byte, K: kilobytes, M:mega-bytes")
        return render_template("upload.html", container=container, result=msg)
      if segsize:
        unit=segsize[-1]
        size=int(segsize[:-1])
        if "B" == unit:
          segsize= size
        elif "K" == unit:
          segsize=size*1024
        elif "M" == unit:
          segsize= size*1024*1024
      #get file name
      app.logger.warning("segment size: [%s]"%segsize)
      file = request.files['file']
      filename = secure_filename(file.filename)
      if not filename:
        return render_template("upload.html", container=container, result=["please specify a file."])
      app.logger.warning("secure file name: [%s]"%filename)
      absfn=os.path.join(Global.uploaddir, container,  filename)
      if not os.path.exists( os.path.dirname(absfn)):
        os.makedirs(os.path.dirname(absfn))
      file.save(absfn)
      obj=os.path.basename(absfn)
      res=None
      if segsize:
        res=Global.swiftconn.upload_object(container, obj, absfn, segsize)
      else:
        res=Global.swiftconn.upload_object(container, obj, absfn)
      msg=res[1] # a list of messages
    #end if POST
    flash("<p>%s</p>"%("</p><p>".join(res[1]))
    app.logger.warning("<p>%s</p>"%("</p><p>".join(res[1]))
    result=Global.swiftconn.list_objects(container)
    return render_template("list_obj.html",container=container, result=result) 
  #end if loggedin 
  return render_template('login.html', error=None)

@app.route('/')
def index_page():
  return render_template('login.html')

@app.route("/download_obj/", methods=['GET', 'POST'])
def download_obj():
  if Global.isloggedin():
    #container, obj = obj_uri.split("/",1)
    container=request.args.to_dict()["container"]
    obj=request.args.to_dict()["obj"]
    dst=os.sep.join((Global.downloaddir, container, obj))
    if not os.path.exists(os.path.dirname(dst)):
      os.makedirs(os.path.dirname(dst))
    msg=Global.swiftconn.download_object(container, obj, dst) 
    if 1 == msg[0]:
      return "Error:\n %s"%msg[1]  
    return send_file(dst, as_attachment=True) 

@app.route("/delete_obj/", methods=['GET', 'POST'])
def delete_obj():
  if Global.isloggedin():
    #container, obj = obj_uri.split("/",1)
    container=request.args.to_dict()["container"]
    obj=request.args.to_dict()["obj"]
    app.logger.warning("delete keys:%s %s----------------"%(container, obj))
    msg=Global.swiftconn.delete_object(container, obj)
    result=Global.swiftconn.list_objects(container)
    flash(msg[1])
    details=""
    #if 0 == result[0]:
    #  details="".join(["<p>%s : %s</p>"%(x, result[1][x]) for x in result[1]])
    app.logger.warning(details)
    return render_template("list_obj.html",container=container, result=result, details=details) 
  return render_template('login.html')

@app.route("/home/<container>/", methods=['GET', 'POST'])
@app.route("/home/", methods=['GET', 'POST'])
def home(container=None):
  if Global.isloggedin():
    args=request.args.to_dict()
    app.logger.warning(str(args))
    if not args: #container is None:
      result=Global.swiftconn.list_containers()
      return render_template("list.html", result=result) 
    else:
      container=args["container"]
      result=Global.swiftconn.list_objects(container)
      return render_template("list_obj.html",container=container, result=result) 
  return render_template('login.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
  error = None
  if request.method == 'POST':
    group, user, pwd=request.form["group"].strip(), request.form["username"].strip(),request.form["password"].strip()
    conn=client.Connection(group, user, pwd)
    if conn.connect():
      Global.setsession(conn) 
      role=Global.swiftconn.get_role()
      flash('You were logged in as %s:%s  %s'%(group, user, [role[1] if role[0] == 0 else " "][0]))
      return redirect(url_for('home'))
    else:
      error="login failed!!!"
  return render_template('login.html', error=error)

@app.route("/test")
def test():
  return render_template("test.html")

@app.route('/logout')
def logout():
    Global.unsetsession()
    flash('You were logged out')
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
