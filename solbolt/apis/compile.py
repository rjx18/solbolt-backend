from flask_restplus import Namespace, Resource, fields
from flask import request
from solc import compile_standard
from solc.exceptions import SolcError
import traceback

api = Namespace('compile', description='Compilation operations')

solc_details = api.model('Solidity Compiler Details',
                {
                    'peephole': fields.Boolean(default=True),
                    'inliner': fields.Boolean(default=True),
                    'jumpdestRemover': fields.Boolean(default=True),
                    'orderLiterals': fields.Boolean(default=False),
                    'deduplicate': fields.Boolean(default=False),
                    'cse': fields.Boolean(default=False),
                    'constantOptimizer': fields.Boolean(default=False),
                    'yul': fields.Boolean(default=False),
                })

solc_settings = api.model('Solidity Compiler Settings',
                {
                    'enable_optimizer': fields.Boolean(default=True, 
                            description="Enables the solidity optimizer. Default is True."),
                    'optimize_runs': fields.Integer(default=200,
                            description="Number of runs for the solidity optimizer to run for"),
                    'evmVersion': fields.String(default='berlin',
                            description="EVM version to compile code for. Default is 'berlin'"),
                    'viaIR': fields.Boolean(default=False, 
                            description="Change compilation pipeline to go through the Yul intermediate representation. This is false by default."),
                    'details': fields.Nested(solc_details, 
                            description="Details for changing optimization behavior. If nothing is specified, the default optimization settings are followed."),
                })

solidity_model = api.model('Compile Solidity', 
		{
            'content': fields.String(required = True, 
					description="Solidity code", 
					help="Solidity cannot be blank."),
            'settings': fields.Nested(solc_settings, 
                    required = True, 
                    description="Settings for the solidity compiler"),
        }
    )

@api.route('/')
class Compile(Resource):
    @api.doc('compile', responses={ 200: 'OK', 400: 'Invalid Argument', 500: 'Mapping Key Error' })
    @api.expect(solidity_model)
    def post(self):
        '''Compile Solidity into EVM'''
        try:
            sol = request.json['content']
            settings = request.json['settings']
            
            optimizer_settings = {
                        "enabled": settings['enable_optimizer'],
                        "runs": settings['optimize_runs'],
                    }
            
            if (settings['details']):
                optimizer_settings["details"] = settings['details']
            
            result = compile_standard({
                'language': 'Solidity', 
                'sources': {
                    'output.sol': {
                        'content': sol}
                    },
                'settings': {
                    "optimizer": optimizer_settings,
                    "evmVersion": settings['evmVersion'],
                    "viaIR": settings['viaIR'],
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