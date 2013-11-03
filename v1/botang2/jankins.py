import os
from flask import Flask, Response, request, render_template
from werkzeug.wsgi import SharedDataMiddleware
import jinja2
#jinja = jinja2.Environment(loader = jinja2.FileSystemLoader(os.path.dirname(__file__) + "/templates"))

print os.path.basename(__file__)
print os.path.dirname(__file__)
app = Flask(os.path.basename(__file__))
#app.wsgi_app = SharedDataMiddleware(app.wsgi_app, {
#  '/bootstrap': os.path.dirname(__file__) + '/bootstrap',
#}, cache=False)

@app.route('/')
def hello_world():
  #return Response(jinja.get_template("jankins.html").render({
  #}), mimetype="text/html")
  app.logger.warning( request.url)
  return render_template("home.html")
if __name__ == "__main__":
  app.run(debug=True, host="0.0.0.0", port=5050)
