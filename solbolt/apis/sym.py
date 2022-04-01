from flask_restplus import Namespace, Resource, fields
from flask import request
from solc import compile_standard
from solc.exceptions import SolcError
import traceback
import json

from .symexec import SymExec

api = Namespace('sym', description='Symbolic execution operations')

solidity_model = api.model('Symbolic Execute', 
		  {'content': fields.String(required = True, 
					 description="Solidity code", 
					 help="Solidity cannot be blank."),
     'json': fields.String(required = True,
                           description="Compiled JSON", 
					                  help="JSON cannot be blank.")})

@api.route('/')
class Symbolic(Resource):
    @api.doc('symexec', responses={ 200: 'OK', 400: 'Invalid Argument', 500: 'Mapping Key Error' })
    @api.expect(solidity_model)
    def post(self):
        '''Symbolically execute Solidity'''
        try:
            solidity_contents = request.json['content']
            compiled_json = json.loads(request.json['json'])
            exec_env = SymExec(solidity_files=['output.sol'],
                solidity_file_contents=[solidity_contents],
                json=[compiled_json])
            
            exec_env.execute_command()
            
            (creation_transaction_gas_map, runtime_transaction_gas_map, function_gas_map) = exec_env.parse_exec_results()
            
            creation_result = { k: v.__dict__() for k, v in creation_transaction_gas_map.items() }
            
            runtime_result = { k: v.__dict__() for k, v in runtime_transaction_gas_map.items() }
            
            return {
                "creation": creation_result,
                "runtime": runtime_result
            }
            
            # TODO: hard coded only one contract here, allow multiple contracts in future
            # contract_names = list(compiled_json["contracts"]["output.sol"].keys())
            
            # if (len(contract_names) == 0):
            #   raise RuntimeError('No valid contracts found')
                        
            # contract_to_analyse = contract_names[0]
            
            # creation_source_map = compiled_json["contracts"]["output.sol"][contract_to_analyse]["bytecode"]["sourceMap"]
            # runtime_source_map = compiled_json["contracts"]["output.sol"][contract_to_analyse]["deployedBytecode"]["sourceMap"]
            # source_ast = compiled_json["sources"]["output.sol"]["ast"]
        except KeyError as e:
            api.abort(500, e.__doc__, status = "Internal server error, could not symbolic execute", statusCode = "500")
        except RuntimeError as e:
            api.abort(500, e.__doc__, status = "Runtime error, could not symbolic execute", statusCode = "500")
        except Exception as e:
            api.abort(400, e.__doc__, status = "Request error, could not symbolic execute", statusCode = "400")

    def parseSourceMap():
      '''Takes in source map, splits it, and then '''
      pass
    
    
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