import requests
import os
import json
from solbolt.tasks import compile_solidity, symbolic_exec
from statistics import median, mean

from os.path import exists
import ast

import traceback

CONTRACT_INDEX_URL = "https://raw.githubusercontent.com/tintinweb/smart-contract-sanctuary-ethereum/71f4a95fb5394c810238952dace1b2c3103e7617/contracts/mainnet/contracts.json"
ETHERSCAN_API_ENDPOINT = 'https://api.etherscan.io/api'
ETHERSCAN_API_KEY = os.environ.get("REACT_APP_SOLBOLT_ETHERSCAN_KEY")

ETHERSCAN_SOURCE = "SourceCode"
ETHERSCAN_LANGUAGE = "language"
ETHERSCAN_SOURCES = "sources"
ETHERSCAN_CONTENT = "content"
ETHERSCAN_RESULT = "result"
ETHERSCAN_COMPILER_VERSION = "CompilerVersion"
ETHERSCAN_OPTIMIZATION_USED = "OptimizationUsed"
ETHERSCAN_RUNS = "Runs"
ETHERSCAN_EVM_VERSION = "EVMVersion"
ETHERSCAN_SETTINGS = "settings"

COMPILER_PEEPHOLE = 'peephole'
COMPILER_INLINER = 'inliner'
COMPILER_JUMPDESTREMOVER = 'jumpdestRemover'
COMPILER_ORDERLITERALS = 'orderLiterals'
COMPILER_DEDUPLICATE = 'deduplicate'
COMPILER_CSE = 'cse'
COMPILER_CONSTANTOPTIMIZER = 'constantOptimizer'
COMPILER_YUL = 'yul'

COMPILER_ENABLE = 'enable_optimizer'
COMPILER_RUNS = 'optimize_runs'
COMPILER_EVM = 'evmVersion'
COMPILER_VIAIR = 'viaIR'
COMPILER_DETAILS = 'details'
COMPILER_VERSION = 'version'
COMPILER_DETAILS_ENABLED = 'details_enabled'

MAX_NUMBER_OF_TX_FOR_EACH_FUNCTION = 30

MIN_TX_COUNT = 50
MIN_TXNS = 20

MAX_PAGES = 10

GAS_CLASSES = [2500, 5000, 10000, 20000, 50000, 100000, 500000, 1000000]

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

DEFAULT_SYMEXEC_SETTINGS = {
    'max_depth': 256,
    'call_depth_limit': 32,
    'strategy': 'bfs',
    'loop_bound': 10,
    'transaction_count': 2
    # 'enable_onchain': fields.Boolean(default=False,
    #         description="Enables on chain concrete execution"),
    # 'onchain_address': fields.String(description="Address used for on chain concrete execution"),
  }

def contract_ether_key(e):
  balance_str = e["balance"][:-6].replace(",", "") 
  if (balance_str == ""):
    return 0
  return float(balance_str)

def contract_tx_key(e):
  return int(e["txcount"])

def read_file(filename):
    contracts = list()
    with open(filename) as f:
        for i, line in enumerate(f):
            contracts.append(json.loads(line))
            
    contracts.sort(reverse=True, key=contract_tx_key)
    return (contracts, i + 1)

# Takes a code and address for a smart contract to test, compiles it, and symbolically executes it
# if there are Etherscan transaction avaliable for us to test.

# We only test if there are more than 25 Etherscan transactions available

# Then, evaluates the accuracy of the gas estimation by polling Etherscan
# Returns the median and average accuracy obtained for each function
class Evaluator:
  def __init__(self, address: str, contract_name: str) -> None:
      print(f"{bcolors.OKBLUE}[EVAL]: Starting evaluation for {contract_name} at {address}...{bcolors.ENDC}")
    
      self.address = address
      self.contract_name = contract_name
      
      self.compiler_settings = None
      self.source_contents = list()
      
  # runs the all the evaluation steps
  def run_all(self) -> None:
    try:
      self.get_etherscan_code()
      compilation_result = self.compile()
      print(f"{bcolors.OKBLUE}[EVAL]: Compilation completed! Starting symbolic execution...{bcolors.ENDC}")
      symexec_result = self.symexec(compilation_result)
      print(f"{bcolors.OKBLUE}[EVAL]: Symexec completed! Evaluating with concrete transactions...{bcolors.ENDC}")
      eval_result = self.eval(symexec_result)
      print(f"{bcolors.OKBLUE}[EVAL]: Evaluation completed! Saving...{bcolors.ENDC}")
      output_dict = {
        "status": 1,
        "result": eval_result
      }
      self.save_to_file(str(output_dict))
    except Exception as e:
      print(f"{bcolors.FAIL}[EVAL]: {e.__class__.__name__} caught! Skipping...{bcolors.ENDC}")
      output_dict = {
        "status": 0,
        "result": f"{e.__class__.__name__} caught",
        "traceback": traceback.format_exc()
      }
      self.save_to_file(str(output_dict))
      

  # gets Etherscan code
  def get_etherscan_code(self):
    etherscan_response = requests.get(ETHERSCAN_API_ENDPOINT, params={
      "module": 'contract',
      "action": 'getsourcecode',
      "address": self.address,
      "apikey": ETHERSCAN_API_KEY
    })
    
    if (etherscan_response.status_code != 200):
      raise EtherscanException
    
    etherscan_data = etherscan_response.json()
    
    result: str = etherscan_data["result"][0]
    
    if (result[ETHERSCAN_SOURCE] != ""):
      detailed_optimizer_settings = dict()
      has_detail = False
      
      if (result[ETHERSCAN_SOURCE].startswith('{')):
        parsed_source = result[ETHERSCAN_SOURCE][1:-1]
        
        source_code = json.loads(parsed_source)
        
        if (source_code[ETHERSCAN_LANGUAGE] != "solidity"):
          raise UnsupportedLanguageException
      
      
        sources = source_code[ETHERSCAN_SOURCES]
        
        for source_filename, source_content in sources.items():
          new_source = {
            "name": source_filename,
            "content": source_content
          }
          
          self.source_contents.append(new_source)
          
        optimizer_details = self.safe_access(source_code, [ETHERSCAN_SETTINGS, 'optimizer', 'details'])
        
        if (optimizer_details is not None):
          has_detail = True
          detailed_optimizer_settings = optimizer_details
          
      else:
        new_source = {
            "name": f'{self.contract_name}.sol',
            "content": result[ETHERSCAN_SOURCE]
          }
        
        self.source_contents.append(new_source)
      
      self.compiler_settings = {
        COMPILER_VERSION: result[ETHERSCAN_COMPILER_VERSION],
        COMPILER_EVM: result[ETHERSCAN_EVM_VERSION],
        COMPILER_RUNS: int(result[ETHERSCAN_RUNS]),
        COMPILER_ENABLE: result[ETHERSCAN_OPTIMIZATION_USED] == "1",
        COMPILER_VIAIR: False,
        COMPILER_DETAILS_ENABLED: has_detail,
        COMPILER_DETAILS: {
          COMPILER_PEEPHOLE: True,
          COMPILER_INLINER: True,
          COMPILER_JUMPDESTREMOVER: True,
          COMPILER_ORDERLITERALS: False,
          COMPILER_DEDUPLICATE: False,
          COMPILER_CSE: False,
          COMPILER_CONSTANTOPTIMIZER: False,
          COMPILER_YUL: False,
          **detailed_optimizer_settings
        }
      }
    else:
      raise EtherscanException
    
  
  def compile(self):
    compilation_result = compile_solidity(self.source_contents, self.compiler_settings)
    if (not compilation_result["success"]):
      raise CompilationFailedException
      
    return compilation_result["result"]
    
  def symexec(self, compilation_result):
    symexec_settings = {
      **DEFAULT_SYMEXEC_SETTINGS,
      'enable_onchain': True,
      'onchain_address': self.address
    }
    
    symexec_result = symbolic_exec(self.source_contents, self.contract_name, compilation_result, symexec_settings)
  
    if (not symexec_result["success"]):
      raise SymExecFailedException
    
    return symexec_result["result"]
  
  # Outputs:
  # Overall summary: Stats for mean, median and sum overall accuracy (% of estimated gas over actual gas), total number of txns tested
  # Per function stats: Overall accuracy (mean, median and sum) for each function, number of concrete instances compared
  def eval(self, symexec_result):
    symexec_gas_map = symexec_result["function_gas"]
    overall_accuracy = list()
    per_function_stats = dict()
    per_gas_class_stats = [list() for _ in GAS_CLASSES]
    
    per_gas_class_stats.append(list())
    
    current_page = 1
    current_txns = 0
    
    no_more_txns = False
    
    function_map = {k[:10]: v for k, v in symexec_gas_map.items()}
    
    for key in function_map.keys():
      per_function_stats[key] = list()   
      
    while ((current_page < MAX_PAGES or current_txns < MIN_TX_COUNT) and not no_more_txns):
      etherscan_tx_response = requests.get(ETHERSCAN_API_ENDPOINT, params={
        "module": 'account',
        "action": 'txlist',
        "address": self.address,
        "startblock": 0,
        "endblock": 99999999,
        "page": current_page,
        "offset": 1000,
        "sort": "desc",
        "apikey": ETHERSCAN_API_KEY
      })
      
      etherscan_txns_data = etherscan_tx_response.json()
      
      if (etherscan_txns_data["status"] == "0"):
        no_more_txns = True
      else:
        etherscan_txns = etherscan_txns_data["result"]
        
        for txn_data in etherscan_txns:
          fn_hash = txn_data["input"][:10]
          if fn_hash in function_map:
            if len(per_function_stats[fn_hash]) >= MAX_NUMBER_OF_TX_FOR_EACH_FUNCTION:
              continue
            
            symexec_gas_estimate = function_map[fn_hash]
            concrete_gas_used = int(txn_data["gasUsed"])
            
            accuracy = symexec_gas_estimate / concrete_gas_used
            
            overall_accuracy.append(accuracy)
            per_function_stats[fn_hash].append(accuracy)
            
            try: 
              gas_class = next(index for index, value in enumerate(GAS_CLASSES) if value > symexec_gas_estimate)
            except StopIteration:
              gas_class = -1
              
            per_gas_class_stats[gas_class].append(accuracy)
            current_txns += 1
      
      current_page += 1
    
    if (len(overall_accuracy) > 0):
      overall_summary = self.get_accuracy_summary(overall_accuracy)
    else:
      raise NoMatchingTransactionsException
    
    per_function_summary = dict()
    
    for key in per_function_stats.keys():
      function_txn_list = per_function_stats[key]
      if (len(function_txn_list) > 0):
        function_summary = self.get_accuracy_summary(function_txn_list)
        per_function_summary[key] = function_summary
  
    per_gas_class_summary = dict()
    for index, gas_class_txns in enumerate(per_gas_class_stats):
      if (len(gas_class_txns) > 0):
        gas_class_summary = self.get_accuracy_summary(gas_class_txns)
        per_gas_class_summary[index] = gas_class_summary
  
    return {
      "summary": overall_summary,
      "functions": per_function_summary,
      "gas_class": per_gas_class_summary
    }
  
  def save_to_file(self, result):
    with open(f"eval/contracts/{self.address}.txt", "w") as result_file:
          result_file.write(result)
  
  def get_accuracy_summary(self, txn_list):
    sum_accuracy = sum(txn_list)
    mean_accuracy = mean(txn_list)
    median_accuracy = median(txn_list)
    number_of_txns = len(txn_list)
    
    return {
      "sum": sum_accuracy,
      "mean": mean_accuracy,
      "median": median_accuracy,
      "count": number_of_txns
    }
  
  def safe_access(self, source, path):
    current_item = source
    
    for item in path:
      current_item = current_item.get(item, None)
      if (current_item is None):
        return None

    return current_item

class Error(Exception):
    """Base class for other exceptions"""
    pass    
  
class EtherscanException(Error):
  pass

class UnsupportedLanguageException(Error):
  pass
  
class UnsupportedSettingsException(Error):
  pass

class CompilationFailedException(Error):
  pass
  
class SymExecFailedException(Error):
  pass
  
class NoMatchingTransactionsException(Error):
  pass
  
# Gets the code and address for the next smart contract to test, and saves progress
# Also saves in separate files the result for individual smart contracts
class EvalWrapper:
  def __init__(self) -> None:
      (self.contracts_list, self.total_contracts) = read_file("contracts.json")
    
  def exec_eval(self):
    num_contracts_analysed = 0
    
    while num_contracts_analysed < self.total_contracts:
      current_contract_json = self.contracts_list[num_contracts_analysed]
      num_contracts_analysed += 1
      
      print(f"{bcolors.OKGREEN}[WRAPPER]: Analysing {num_contracts_analysed}/{self.total_contracts} contracts: {current_contract_json['name']} at {current_contract_json['address']}, with balance {current_contract_json['balance']}...{bcolors.ENDC}")
      
      if (os.path.exists(f"eval/contracts/{current_contract_json['address']}.txt")):
        print(f"{bcolors.OKGREEN}[WRAPPER]: Contract already analysed! Skipping...{bcolors.ENDC}")
        continue
      
      if (current_contract_json['txcount'] < MIN_TX_COUNT):
        print(f"{bcolors.OKGREEN}[WRAPPER]: Contract only has {current_contract_json['txcount']} transactions, which is lower than the minimum of {MIN_TX_COUNT}. Skipping...{bcolors.ENDC}")
        continue
      
      evaluator = Evaluator(current_contract_json['address'], current_contract_json['name'])
      evaluator.run_all()
    
    print("Evaluation complete!")
    
class ResultParser:
  def __init__(self) -> None:
      pass
    
  def exec_parse(self):
    contract_directory = 'eval/contracts'
    success_count = 0
    total_accuracy = 0
    count_accuracy = 0
    for filename in os.listdir(contract_directory):
      full_filename = os.path.join(contract_directory, filename)
      # checking if it is a file
      if os.path.isfile(full_filename):
        with open(full_filename) as f:
          json_content = ast.literal_eval(f.read())
          if (json_content["status"] == 1):
            success_count += 1
            total_accuracy += json_content["result"]["summary"]["sum"]
            count_accuracy += json_content["result"]["summary"]["count"]
    print(success_count)
    print(total_accuracy / count_accuracy)
        
    
if __name__ == "__main__":
  # test_wrapper = EvalWrapper()
  # test_wrapper.exec_eval()
  
  result_parser = ResultParser()
  result_parser.exec_parse()
  # test_eval = Evaluator("0x2c4e8f2d746113d0696ce89b35f0d8bf88e0aeca", "SimpleToken")
  # test_eval.run_all()