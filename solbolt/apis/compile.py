from flask_restplus import Namespace, Resource, fields
from flask import request
import traceback
from mythril.exceptions import CompilerError
import json
from subprocess import PIPE, Popen

from json.decoder import JSONDecodeError

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
            'content': fields.String(required = True, 
					description="Solidity code", 
					help="Solidity cannot be blank."),
            'settings': fields.Nested(solc_settings, 
                    required = True, 
                    description="Settings for the solidity compiler"),
        }
    )

solc_binaries = [
    'v0.8.13+commit.abaa5c0e',
    'v0.8.12+commit.f00d7308',
    'v0.8.11+commit.d7f03943',
    'v0.8.10+commit.fc410830',
    'v0.8.9+commit.e5eed63a',
    'v0.8.8+commit.dddeac2f',
    'v0.8.7+commit.e28d00a7',
    'v0.8.6+commit.11564f7e',
    'v0.8.5+commit.a4f2e591',
    'v0.8.4+commit.c7e474f2',
    'v0.8.3+commit.8d00100c',
    'v0.8.2+commit.661d1103',
    'v0.8.1+commit.df193b15',
    'v0.8.0+commit.c7dfd78e',
    'v0.7.6+commit.7338295f',
    'v0.7.5+commit.eb77ed08',
    'v0.7.4+commit.3f05b770',
    'v0.7.3+commit.9bfce1f6',
    'v0.7.2+commit.51b20bc0',
    'v0.7.1+commit.f4a555be',
    'v0.7.0+commit.9e61f92b',
    'v0.6.12+commit.27d51765',
    'v0.6.11+commit.5ef660b1',
    'v0.6.10+commit.00c0fcaf',
    'v0.6.9+commit.3e3065ac',
    'v0.6.8+commit.0bbfe453',
    'v0.6.7+commit.b8d736ae',
    'v0.6.6+commit.6c089d02',
    'v0.6.5+commit.f956cc89',
    'v0.6.4+commit.1dca32f3',
    'v0.6.3+commit.8dda9521',
    'v0.6.2+commit.bacdbe57',
    'v0.6.1+commit.e6f7d5a4',
    'v0.6.0+commit.26b70077',
    'v0.5.17+commit.d19bba13',
    'v0.5.16+commit.9c3226ce',
    'v0.5.15+commit.6a57276f',
    'v0.5.14+commit.01f1aaa4',
    'v0.5.13+commit.5b0b510c',
    'v0.5.12+commit.7709ece9',
    'v0.5.11+commit.22be8592',
    'v0.5.10+commit.5a6ea5b1',
    'v0.5.9+commit.c68bc34e',
    'v0.5.8+commit.23d335f2',
    'v0.5.7+commit.6da8b019',
    'v0.5.6+commit.b259423e',
    'v0.5.5+commit.47a71e8f',
    'v0.5.4+commit.9549d8ff',
    'v0.5.3+commit.10d17f24',
    'v0.5.2+commit.1df8f40c',
    'v0.5.1+commit.c8a2cb62',
    'v0.5.0+commit.1d4f565a',
    'v0.4.26+commit.4563c3fc',
    'v0.4.25+commit.59dbf8f1',
    'v0.4.24+commit.e67f0147',
    'v0.4.23+commit.124ca40d',
    'v0.4.22+commit.4cb486ee',
    'v0.4.21+commit.dfe3193c',
    'v0.4.20+commit.3155dd80',
    'v0.4.19+commit.c4cbbb05',
    'v0.4.18+commit.9cf6e910',
    'v0.4.17+commit.bdeb9e52',
    'v0.4.16+commit.d7661dd9',
    'v0.4.15+commit.8b45bddb',
    'v0.4.14+commit.c2215d46',
    'v0.4.13+commit.0fb4cb1a',
    'v0.4.12+commit.194ff033',
    'v0.4.11+commit.68ef5810',
    'v0.4.10+commit.9e8cc01b'
]

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
            
            if settings.get('details', None) and settings.get('details_enabled', False):
                optimizer_settings["details"] = settings['details']
            
            # Check if the version supplied is within the binaries installed, prevent injection attack
            if (settings['version'] not in solc_binaries):
                raise CompilerError(
                    f"Compiler version not found: {settings['version']}"
                )
            
            sources = {
                    'output.sol': {
                            'content': sol
                        }
                    }
            
            json_settings = {
                    "optimizer": optimizer_settings,
                    "evmVersion": settings['evmVersion'],
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
                    }
            
            if (settings['viaIR']):
                json_settings["viaIR"] = True
            
            solc_binary = f"./solc/solc-linux-amd64-{settings['version']}"
            
            result = get_solc_json(sources, json_settings, solc_binary)
            
            return {
                "status": "Compiled",
                "result": result
            }
        except CompilerError as e:
            api.abort(400, e.__doc__, status = f'Failed to compile Solidity: {str(e)}', statusCode = "400")
        except JSONDecodeError as e:
            api.abort(400, e.__doc__, status = f'Failed to decode EVM output, please try again', statusCode = "400")
        except KeyError as e:
            api.abort(500, e.__doc__, status = "Internal server error, could not compile content", statusCode = "500")
        except Exception as e:
            api.abort(400, e.__doc__, status = "Request error, could not compile content", statusCode = "400")

def get_solc_json(sources, json_settings, solc_binary="solc"):
    """

    :param file:
    :param solc_binary:
    :param solc_settings_json:
    :return:
    """
    cmd = [solc_binary, "--standard-json", "--allow-paths", "."]

    input_json = json.dumps(
        {
            "language": "Solidity",
            "sources": sources,
            "settings": json_settings,
        }
    )

    try:
        p = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        stdout, stderr = p.communicate(bytes(input_json, "utf8"))

    except FileNotFoundError:
        raise CompilerError(
            "Compiler not found. Make sure that solc is installed and in PATH, or set the SOLC environment variable."
        )

    out = stdout.decode("UTF-8")

    try:
        result = json.loads(out)
    except JSONDecodeError as e:
        print(f"Encountered a decode error, stdout:{out}, stderr: {stderr}")
        raise e

    for error in result.get("errors", []):
        if error["severity"] == "error":
            raise CompilerError(
                "Solc experienced a fatal error - %s" % error["formattedMessage"]
            )

    return result

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