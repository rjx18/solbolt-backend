from flask_restplus import Api

from .compile import api as compile_ns
from .sym import api as sym_ns

api = Api(
    title='Solbolt Backend',
    version='1.0',
    description='A description',
    # All API metadatas
)

api.add_namespace(compile_ns)
api.add_namespace(sym_ns)