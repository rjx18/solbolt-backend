from flask_restplus import Namespace, Resource, fields
from flask import request
from ..tasks import symbolic_exec, celery
import json

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
                    'enable_onchain': fields.Boolean(default=False,
                            description="Enables on chain concrete execution"),
                    'onchain_address': fields.String(description="Address used for on chain concrete execution"),
                })

sym_file = api.model('Symbolic execution file',
                {
                    'name': fields.String(description="Filename", required=True),
                    'content': fields.String(description="Solidity content", required=True),
                })

solidity_model = api.model('Symbolic Execute', 
		  { 'files': fields.List(fields.Nested(sym_file), description='Solidity files', required=True),
            'json': fields.String(required = True,
                            description="Compiled JSON", 
					                  help="JSON cannot be blank."),
            'contract': fields.String(required = True, description="Name of contract to symbolically execute"),
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
        solidity_files = request.json['files']
        contract = request.json['contract']
        compiled_json = json.loads(request.json['json'])
        settings = request.json['settings']
        task = symbolic_exec.delay(solidity_files, contract, compiled_json, settings)
        return {"task_id": task.id}
    
@api.route('/<task_id>')
class SymbolicStatus(Resource):
    def get(self, task_id):
        task_result = celery.AsyncResult(task_id)
        result = {
            "task_id": task_id,
            "task_status": task_result.status,
            "task_result": task_result.result
        }
        return result