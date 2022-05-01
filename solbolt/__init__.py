import os

from flask import Flask
try: 
    from flask_restplus import Api, Resource
except ImportError:
    import werkzeug, flask.scaffold
    werkzeug.cached_property = werkzeug.utils.cached_property
    flask.helpers._endpoint_from_view_func = flask.scaffold._endpoint_from_view_func
    from flask_restplus import Api, Resource
from solbolt.apis import api
from flask_cors import CORS

def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        DATABASE=os.path.join(app.instance_path, 'flaskr.sqlite'),
    )

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    api.init_app(app)
    
    CORS(app, resources={r'/*': {'origins': '*'}})
    
    # app = Api(app = flask_app)
    # name_space = app.namespace('main', description='Main APIs')

    # # a simple page that says hello
    # # @app.route('/hello')
    # # def hello():
    # #     return 'Hello, World!'

    # @name_space.route("/")
    # class Compile(Resource):
    #   def get(self):
    #     return {
    #       "status": "Got new data"
    #     }
    #   def post(self):
    #     return {
    #       "status": "Posted new data"
    #     }

    return app