import os
import time

from celery import Celery

from mythril.exceptions import CompilerError
from json.decoder import JSONDecodeError
import json

from subprocess import PIPE, Popen

from .apis.symexec import SymExec

import traceback

celery = Celery(__name__)
celery.conf.broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379")
celery.conf.result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379")
celery.conf.worker_redirect_stdouts = False

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

@celery.task(name="compile_solidity")
def compile_solidity(sol_files, settings):
  try:
    sources = dict()
    
    for file in sol_files:
        sources[file['name']] = {
            'content': file['content']
        }
    
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
    
    json_settings = {
            "optimizer": optimizer_settings,
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
        
    if (settings['evmVersion'] != 'Default'):
        json_settings["evmVersion"] = settings['evmVersion']
    
    solc_binary = f"./solc/solc-linux-amd64-{settings['version']}"
    
    result = get_solc_json(sources, json_settings, solc_binary)
    
    return {
        "success": True,
        "result": result
    }
    
  except CompilerError as e:
      return {
        "success": False,
        "result": f'Failed to compile Solidity: {str(e)}'
      }
  except JSONDecodeError as e:
      return {
        "success": False,
        "result": 'Failed to decode EVM output, please try again'
      }
  except KeyError as e:
      return {
        "success": False,
        "result": "Internal server error, could not compile content"
      }
  except Exception as e:
      print(traceback.format_exc())
      return {
        "success": False,
        "result": "Request error, could not compile content: " + traceback.format_exc()
      }
  
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
        # print(f"Encountered a decode error, stdout:{out}, stderr: {stderr}")
        raise e

    for error in result.get("errors", []):
        if error["severity"] == "error":
            raise CompilerError(
                "Solc experienced a fatal error - %s" % error["formattedMessage"]
            )

    return result
  
@celery.task(name="symbolic_exec")
def symbolic_exec(solidity_files, contract, compiled_json, settings):
  try:
    onchain_address = settings.get('onchain_address', None) if settings['enable_onchain'] else None
    no_onchain_data = not settings['enable_onchain']
    
    exec_env = SymExec(solidity_files=solidity_files,
                onchain_address=onchain_address,
                contract_name=contract,
                json=[compiled_json],
                max_depth=settings['max_depth'],
                call_depth_limit=settings['call_depth_limit'],
                strategy=settings['strategy'],
                loop_bound=settings['loop_bound'],
                transaction_count=settings['transaction_count'],
                no_onchain_data=no_onchain_data
            )
            
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
      "success": True,
      "result": {
        "creation": creation_result,
        "runtime": runtime_result,
        "function_gas": function_gas_map,
        "loop_gas": loop_gas_result
      }
    }
    
  except KeyError as e:
    # print(traceback.format_exc())
    return {
        "success": False,
        "result": "Internal server error, could not symbolic execute"
      }
  except RuntimeError as e:
    return {
        "success": False,
        "result": "Runtime error, could not symbolic execute"
      }
  except Exception as e:
    return {
        "success": False,
        "result": traceback.format_exc()
      }
