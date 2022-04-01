from flask_restplus import Namespace, Resource, fields
from flask import request
from solc import compile_standard
from solc.exceptions import SolcError
import traceback

api = Namespace('compile', description='Compilation operations')

solidity_model = api.model('Compile Solidity', 
		  {'content': fields.String(required = True, 
					 description="Solidity code", 
					 help="Solidity cannot be blank.")})

@api.route('/')
class Compile(Resource):
    @api.doc('compile', responses={ 200: 'OK', 400: 'Invalid Argument', 500: 'Mapping Key Error' })
    @api.expect(solidity_model)
    def post(self):
        '''Compile Solidity into EVM'''
        try:
            sol = request.json['content']
            result = compile_standard({
                'language': 'Solidity', 
                'sources': {
                    'output.sol': {
                        'content': sol}
                    },
                'settings': {
                    "optimizer": {"enabled": False},
                    'outputSelection': {
                        "*": {
                                "": ["ast"],
                                "*": [
                                    "metadata",
                                    "evm.bytecode",
                                    "evm.legacyAssembly",
                                    "evm.deployedBytecode",
                                    "evm.methodIdentifiers",
                                    "ir"
                                ],
                            },
                        },
                    },
                })
            return {
                "status": "Compiled",
                "result": result
            }
        except SolcError as e:
            api.abort(400, e.__doc__, status = f'Failed to compile Solidity: {str(e)}', statusCode = "400")
        except KeyError as e:
            api.abort(500, e.__doc__, status = "Internal server error, could not compile content", statusCode = "500")
        except Exception as e:
            api.abort(400, e.__doc__, status = "Request error, could not compile content", statusCode = "400")

# @api.route('/<id>')
# @api.param('id', 'The cat identifier')
# @api.response(404, 'Cat not found')
# class Cat(Resource):
#     @api.doc('get_cat')
#     @api.marshal_with(cat)
#     def get(self, id):
#         '''Fetch a cat given its identifier'''
#         for cat in CATS:
#             if cat['id'] == id:
#                 return cat
#         api.abort(404)