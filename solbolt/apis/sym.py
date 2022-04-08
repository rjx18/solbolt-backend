from flask_restplus import Namespace, Resource, fields
from flask import request
from solc import compile_standard
from solc.exceptions import SolcError
import traceback
import json

from .symexec import SymExec

api = Namespace('sym', description='Symbolic execution operations')

sym_settings = api.model('Symbolic execution Settings',
                {
                    'max_depth': fields.Integer(default=128),
                    'call_depth_limit': fields.Integer(default=10),
                    'strategy': fields.String(default='bfs', 
                                              description="Search strategy for symbolic execution. Can be 'bfs', 'dfs', 'naive-random' or 'weighted-random'"),
                    'loop_bound': fields.Integer(default=10,
                            description="Number of loop iterations to execute before stopping."),
                    'transaction_count': fields.Integer(default=2,
                            description="Number of transaction states to symbolically execute."),
                })

solidity_model = api.model('Symbolic Execute', 
		  { 'content': fields.String(required = True, 
					 description="Solidity code", 
					 help="Solidity cannot be blank."),
            'json': fields.String(required = True,
                            description="Compiled JSON", 
					                  help="JSON cannot be blank."),
            'settings': fields.Nested(sym_settings, required = True,
                            description="Settings for symbolic execution", 
					                  help="Settings cannot be blank.")
            })

@api.route('/')
class Symbolic(Resource):
    @api.doc('symexec', responses={ 200: 'OK', 400: 'Invalid Argument', 500: 'Mapping Key Error' })
    @api.expect(solidity_model)
    def post(self):
        '''Symbolically execute Solidity'''
        try:
            solidity_contents = request.json['content']
            compiled_json = json.loads(request.json['json'])
            settings = request.json['settings']
            
            exec_env = SymExec(solidity_files=['output.sol'],
                solidity_file_contents=[solidity_contents],
                json=[compiled_json],
                max_depth=settings['max_depth'],
                call_depth_limit=settings['call_depth_limit'],
                strategy=settings['strategy'],
                loop_bound=settings['loop_bound'],
                transaction_count=settings['transaction_count'])
            
            exec_env.execute_command()
            
            (creation_transaction_gas_map, runtime_transaction_gas_map, function_gas_map, loop_gas_meter) = exec_env.parse_exec_results()
            
            creation_result = { k: v.__dict__() for k, v in creation_transaction_gas_map.items() }
            
            runtime_result = { k: v.__dict__() for k, v in runtime_transaction_gas_map.items() }
            
            loop_gas_result = dict()
            
            for key in loop_gas_meter.keys():
                loop_gas_result[key] = dict()
                
                key_gas_items = loop_gas_meter[key]
                
                for pc in key_gas_items.keys():
                    loop_gas_result[key][pc] = dict()
                    loop_gas_item = key_gas_items[pc]
                    
                    if len(loop_gas_item.iteration_gas_cost) > 0:
                        average_iteration_cost = sum(loop_gas_item.iteration_gas_cost) / len(loop_gas_item.iteration_gas_cost)
                    else:
                        average_iteration_cost = 0
                    
                    loop_gas_result[key][pc] = average_iteration_cost
            
            return {
                "creation": creation_result,
                "runtime": runtime_result,
                "loop_gas": loop_gas_result
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