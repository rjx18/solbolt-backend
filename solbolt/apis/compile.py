from flask_restplus import Namespace, Resource, fields
from flask import request, jsonify
import traceback
from mythril.exceptions import CompilerError
import json
from subprocess import PIPE, Popen

from json.decoder import JSONDecodeError

from ..tasks import compile_solidity, celery

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

sol_file = api.model('Compilation file',
                {
                    'name': fields.String(description="Filename", required=True),
                    'content': fields.String(description="Solidity content", required=True),
                })

solc_settings = api.model('Solidity Compiler Settings',
                {
                    'version': fields.String(default='v0.8.13+commit.abaa5c0e',
                            description="Version to compile the solidity file with"),
                    'enable_optimizer': fields.Boolean(default=True, 
                            description="Enables the solidity optimizer. Default is True."),
                    'optimize_runs': fields.Integer(default=200,
                            description="Number of runs for the solidity optimizer to run for"),
                    'evmVersion': fields.String(default='berlin',
                            description="EVM version to compile code for. Default is 'berlin'"),
                    'viaIR': fields.Boolean(default=False, 
                            description="Change compilation pipeline to go through the Yul intermediate representation. This is false by default."),
                    'details_enabled': fields.Boolean(default=False, 
                            description="Enables the advanced optimiser details. This is false by default."),
                    'details': fields.Nested(solc_details, 
                            description="Details for changing optimization behavior. If nothing is specified, the default optimization settings are followed."),
                })

solidity_model = api.model('Compile Solidity', 
		{
            'files': fields.List(fields.Nested(sol_file), description='Solidity files', required=True),
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
        sol_files = request.json['files']
        settings = request.json['settings']
        task = compile_solidity.delay(sol_files, settings)
        return {"task_id": task.id}

@api.route('/<task_id>')
class CompileStatus(Resource):
    def get(self, task_id):
        task_result = celery.AsyncResult(task_id)
        result = {
            "task_id": task_id,
            "task_status": task_result.status,
            "task_result": task_result.result
        }
        return result
