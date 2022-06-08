from distutils.log import error
from matplotlib.pyplot import xlabel
import requests
import os
import json
from solbolt.tasks import compile_solidity, symbolic_exec
from statistics import median, mean

from os.path import exists
import ast
from packaging import version

import traceback

import argparse

import sys

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.colors import n_colors
import plotly.express as px

from enum import Enum
import time
from pathlib import Path

############ EVAL #############

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

COV_CLASSES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

def get_gas_class_name(gas_class):
  if gas_class == 0:
    return f'0 - {GAS_CLASSES[gas_class] // 1000}K GAS'
  if gas_class < len(GAS_CLASSES):
    return f'{GAS_CLASSES[gas_class - 1] // 1000}K - {GAS_CLASSES[gas_class] // 1000}K GAS'
  return f'>{GAS_CLASSES[gas_class - 1] // 1000}K GAS'

def get_cov_class_name(cov_class):
  if cov_class == 0:
    return f'0% - {COV_CLASSES[cov_class]}%'
  if cov_class < len(COV_CLASSES):
    return f'{COV_CLASSES[cov_class - 1]}% - {COV_CLASSES[cov_class]}%'
  return f'>{COV_CLASSES[cov_class - 1]}%'

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
    'max_depth': 64,
    'call_depth_limit': 16,
    'strategy': 'bfs',
    'loop_bound': 10,
    'transaction_count': 2,
    'ignore_constraints': True
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
  def __init__(self, address: str, contract_name: str = "contract", symexec_dict=None, prefix=None) -> None:
      print(f"{bcolors.OKBLUE}[EVAL]: Starting evaluation for {contract_name} at {address}...{bcolors.ENDC}")
      if (symexec_dict != None):
        print(f"{bcolors.OKBLUE}[EVAL]: Using loaded symexec results...{bcolors.ENDC}")
    
      self.address = address
      self.contract_name = contract_name
      
      self.symexec_dict = symexec_dict
      
      self.compiler_settings = None
      self.prefix = prefix
      self.source_contents = list()
      
  # runs the all the evaluation steps
  def run_all(self) -> None:
    try:
      if (self.symexec_dict == None):
        self.get_etherscan_code()
        compilation_result = self.compile()
        print(f"{bcolors.OKBLUE}[EVAL]: Compilation completed! Starting symbolic execution...{bcolors.ENDC}")
        symexec_result = self.symexec(compilation_result)
        print(f"{bcolors.OKBLUE}[EVAL]: Symexec completed! Evaluating with concrete transactions...{bcolors.ENDC}")
      else:
        symexec_result = self.symexec_dict
        print(f"{bcolors.OKBLUE}[EVAL]: Symexec loaded from file! Evaluating with concrete transactions...{bcolors.ENDC}")
      eval_result = self.eval(symexec_result)
      print(f"{bcolors.OKBLUE}[EVAL]: Evaluation completed! Saving...{bcolors.ENDC}")
      output_dict = {
        "status": 1,
        "result": eval_result
      }
      self.save_to_file(str(output_dict), prefix=self.prefix)
    except Exception as e:
      print(f"{bcolors.FAIL}[EVAL]: {e.__class__.__name__} caught! Skipping...{bcolors.ENDC}")
      output_dict = {
        "status": 0,
        "result": f"{e.__class__.__name__} caught",
        "traceback": traceback.format_exc()
      }
      self.save_to_file(str(output_dict), prefix=self.prefix)
      

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
      
      if version.parse(result[ETHERSCAN_COMPILER_VERSION]) < version.parse("0.4.18"):
        raise EtherscanException
      
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
              gas_class = next(index for index, value in enumerate(GAS_CLASSES) if value > concrete_gas_used)
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
      "gas_class": per_gas_class_summary,
      "symexec_result": symexec_result
    }
  
  def save_to_file(self, result, prefix=None):
    prefix_text = "" if prefix == None else f'{prefix}/'
    
    path = f"eval/contracts/{prefix_text}"
    
    Path(path).mkdir(parents=True, exist_ok=True)
    
    with open(f"{path}{self.address}.txt", "w") as result_file:
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
    
  def exec_eval_symloaded(self):
    contract_directory = 'eval/contracts/v2'
    contract_directory_v1 = 'eval/contracts'
    for filename in os.listdir(contract_directory):
      full_filename = os.path.join(contract_directory, filename)
      full_filename_v1 = os.path.join(contract_directory_v1, filename)
      # checking if it is a file
      if os.path.isfile(full_filename):
        with open(full_filename) as f:
          json_content = ast.literal_eval(f.read())
          if (json_content["status"] == 0):
            with open(full_filename_v1) as f1:
              json_content_v1 = ast.literal_eval(f1.read())
              if (json_content_v1["status"] == 1):
                evaluator = Evaluator(filename[:-4], symexec_dict=json_content_v1["result"]["symexec_result"], prefix="v2")
                evaluator.run_all()
    
class ResultMode(Enum):
    default = 'default'
    gas = 'gas'
    version = 'version'
    coverage = 'coverage'
    errors = 'errors'

    def __str__(self):
        return self.value
    
class ResultParser:
  
  def __init__(self, mode) -> None:
      self.mode = mode
        
  def default_parse(self):
    contract_directory = 'eval/contracts'
    success_count = 0
    accuracy_list = []
    
    accuracy_classes = [0.5, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5, 1.75, 3.0, 7.0]
    accuracy_class_list = [0 for _ in accuracy_classes]
    accuracy_class_list.append(0)
    
    accuracy_labels = ["<50%", "50% - 80%", "80% - 90%", "90% - 100%", "100% - 110%", "110% - 120%", "120% - 150%", "150% - 175%", "175% - 300%", "300% - 700%", ">700%"]
    
    coverage_list = []
    for filename in os.listdir(contract_directory):
      full_filename = os.path.join(contract_directory, filename)
      # checking if it is a file
      if os.path.isfile(full_filename):
        with open(full_filename) as f:
          json_content = ast.literal_eval(f.read())
          if (json_content["status"] == 1):
            success_count += 1
            accuracy_for_contact = json_content["result"]["summary"]["sum"] / json_content["result"]["summary"]["count"]
            accuracy_list.append(accuracy_for_contact * 100.0)
            coverage_list.append(json_content["result"]["symexec_result"]["cov_percentage"])

            function_gas = json_content["result"]["functions"]

            for function_name, summary in function_gas.items():
              fn_accuracy = summary["mean"]
              try: 
                acc_class = next(index for index, value in enumerate(accuracy_classes) if value > fn_accuracy)
              except StopIteration:
                acc_class = -1
              accuracy_class_list[acc_class] += 1
    
    print(f'Total contracts successfully evaluated: {success_count}')
    print(f'Mean accuracy (estimated gas over exact): {mean(accuracy_list)}')
    print(f'Median accuracy (estimated gas over exact): {median(accuracy_list)}')
    print(f'Mean coverage: {mean(coverage_list)}%')
    print(f'Median coverage: {median(coverage_list)}%')
    accuracy_df = pd.Series(accuracy_list, copy=False)
    coverage_df = pd.Series(coverage_list, copy=False)
    
    layout = go.Layout(
        autosize=False,
        width=400,
        height=500,
    )
    
    fig_acc = go.Figure(data=go.Violin(y=accuracy_df, box_visible=True, line_color='black',
                               meanline_visible=True, fillcolor='lightseagreen', opacity=0.6,
                               x0='Average accuracy per contract', points="all", spanmode="hard"), layout=layout)
    fig_acc.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
    )
    
    fig_acc.write_html(f"eval/plots/overall_accuracy_plot.html")
    
    
    fig_cov = go.Figure(data=go.Violin(y=coverage_df, box_visible=True, line_color='black',
                               meanline_visible=True, fillcolor='salmon', opacity=0.6,
                               x0='Average coverage per contract', points="all", spanmode="hard"), layout=layout)
    fig_cov.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
    )
    fig_cov.write_html(f"eval/plots/overall_cov_plot.html")
    
    accuracy_map_parsed = [{'Accuracy': accuracy_labels[i], 'Count': v} for (i, v) in enumerate(accuracy_class_list)]
    
    acc_map_df = pd.DataFrame.from_records(accuracy_map_parsed)

    fig = px.bar(acc_map_df, x='Accuracy', y='Count')
    fig.update_layout(
        autosize=False,
        width=400,
        height=400,
        margin=dict(l=0, r=0, t=0, b=0)
      )
    fig.write_html(f"eval/plots/overall_fn_accuracy_plot.html")
    
    gastap_map_parsed = [
      {'Accuracy': "<50%", 'Count': 0, 'Type': 'Constant'},
      {'Accuracy': "<50%", 'Count': 0, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': "<50%", 'Count': 0, 'Type': 'Parametric'},
      {'Accuracy': "<50%", 'Count': 0, 'Type': 'Parametric (improved cost models)'},
      {'Accuracy': "50% - 80%", 'Count': 0, 'Type': 'Constant'},
      {'Accuracy': "50% - 80%", 'Count': 0, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': "50% - 80%", 'Count': 0, 'Type': 'Parametric'},
      {'Accuracy': "50% - 80%", 'Count': 0, 'Type': 'Parametric (improved cost models)'},
      {'Accuracy': "80% - 90%", 'Count': 0, 'Type': 'Constant'},
      {'Accuracy': "80% - 90%", 'Count': 0, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': "80% - 90%", 'Count': 0, 'Type': 'Parametric'},
      {'Accuracy': "80% - 90%", 'Count': 0, 'Type': 'Parametric (improved cost models)'},
      {'Accuracy': "90% - 100%", 'Count': 0, 'Type': 'Constant'},
      {'Accuracy': "90% - 100%", 'Count': 0, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': "90% - 100%", 'Count': 0, 'Type': 'Parametric'},
      {'Accuracy': "90% - 100%", 'Count': 0, 'Type': 'Parametric (improved cost models)'},
      {'Accuracy': "100% - 110%", 'Count': 17, 'Type': 'Constant'},
      {'Accuracy': "100% - 110%", 'Count': 19, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': "100% - 110%", 'Count': 3, 'Type': 'Parametric'},
      {'Accuracy': "100% - 110%", 'Count': 3, 'Type': 'Parametric (improved cost models)'},
      {'Accuracy': "110% - 120%", 'Count': 9, 'Type': 'Constant'},
      {'Accuracy': "110% - 120%", 'Count': 29, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': "110% - 120%", 'Count': 3, 'Type': 'Parametric'},
      {'Accuracy': "110% - 120%", 'Count': 8, 'Type': 'Parametric (improved cost models)'},
      {'Accuracy': "120% - 150%", 'Count': 21, 'Type': 'Constant'},
      {'Accuracy': "120% - 150%", 'Count': 28, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': "120% - 150%", 'Count': 5, 'Type': 'Parametric'},
      {'Accuracy': "120% - 150%", 'Count': 16, 'Type': 'Parametric (improved cost models)'},
      {'Accuracy': "150% - 175%", 'Count': 16, 'Type': 'Constant'},
      {'Accuracy': "150% - 175%", 'Count': 0, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': "150% - 175%", 'Count': 0, 'Type': 'Parametric'},
      {'Accuracy': "150% - 175%", 'Count': 0, 'Type': 'Parametric (improved cost models)'},
      {'Accuracy': "175% - 300%", 'Count': 0, 'Type': 'Constant'},
      {'Accuracy': "175% - 300%", 'Count': 0, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': "175% - 300%", 'Count': 0, 'Type': 'Parametric'},
      {'Accuracy': "175% - 300%", 'Count': 0, 'Type': 'Parametric (improved cost models)'},
      {'Accuracy': "300% - 700%", 'Count': 13, 'Type': 'Constant'},
      {'Accuracy': "300% - 700%", 'Count': 0, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': "300% - 700%", 'Count': 16, 'Type': 'Parametric'},
      {'Accuracy': "300% - 700%", 'Count': 0, 'Type': 'Parametric (improved cost models)'},
      {'Accuracy': ">700%", 'Count': 0, 'Type': 'Constant'},
      {'Accuracy': ">700%", 'Count': 0, 'Type': 'Constant (improved cost models)'},
      {'Accuracy': ">700%", 'Count': 0, 'Type': 'Parametric'},
      {'Accuracy': ">700%", 'Count': 0, 'Type': 'Parametric (improved cost models)'},
    ]
    
    gastap_df = pd.DataFrame.from_records(gastap_map_parsed)

    fig_gastap = px.bar(gastap_df, x='Accuracy', y='Count', color='Type', barmode='group')
    fig_gastap.update_layout(
        autosize=False,
        width=700,
        height=400,
        margin=dict(l=0, r=0, t=0, b=0)
      )
    fig_gastap.write_html(f"eval/plots/overall_gastap_fn_accuracy_plot.html")

  def coverage_parse(self):
    contract_directory = 'eval/contracts'
    cov_dict = {c: [] for c in range(len(COV_CLASSES))}
    for filename in os.listdir(contract_directory):
      full_filename = os.path.join(contract_directory, filename)
      # checking if it is a file
      if os.path.isfile(full_filename):
        with open(full_filename) as f:
          json_content = ast.literal_eval(f.read())
          if (json_content["status"] == 1):
            cov_percentage = json_content["result"]["symexec_result"]["cov_percentage"]
            cov_class = next(index for index, value in enumerate(COV_CLASSES) if value > cov_percentage)
            cov_dict[cov_class].append(json_content["result"]["summary"]["mean"] * 100.0)
            
    colors = n_colors('rgb(5, 200, 200)', 'rgb(200, 10, 10)', len(cov_dict), colortype='rgb')

    layout = go.Layout(
        autosize=False,
        width=800,
        height=400,
    )

    fig = go.Figure(layout=layout)
    for index, cov_class in enumerate(sorted(cov_dict)):
        print(f'Cov class {cov_class}: {len(cov_dict[cov_class])}')
        cov_df = pd.Series(cov_dict[cov_class], copy=False)
        fig.add_trace(go.Violin(x=cov_df, name=get_cov_class_name(cov_class), line_color=colors[index], spanmode="hard", box_visible=True, meanline_visible=True))

    fig.update_traces(orientation='h', side='positive', width=3, points=False)
    fig.update_layout(xaxis_showgrid=False, xaxis_zeroline=False, margin=dict(l=0, r=0, t=0, b=0))
    fig.write_html(f"eval/plots/coverage_against_accuracy_plot.html")
    
  def error_parse(self):
    contract_directory = 'eval/contracts'
    error_dict = {
      "Success": 0,
      "Solidity version too low or Etherscan API error": 0,
      "Not enough concrete transactions": 0,
      "Unsupported language": 0,
      "Compilation failed": 0,
      "Symbolic execution failed": 0,
      "Other errors": 0
    }
    for filename in os.listdir(contract_directory):
      full_filename = os.path.join(contract_directory, filename)
      # checking if it is a file
      if os.path.isfile(full_filename):
        with open(full_filename) as f:
          json_content = ast.literal_eval(f.read())
          error_class = "Success"
          
          if (json_content["status"] != 1):
            error_logged = json_content["result"][:-7]
            
            if error_logged.startswith("Etherscan"):
              error_class = "Solidity version too low or Etherscan API error"
            elif error_logged.startswith("NoMatching"):
              error_class = "Not enough concrete transactions"
            elif error_logged.startswith("Unsupported"):
              error_class = "Unsupported language"
            elif error_logged.startswith("Compilation"):
              error_class = "Compilation failed"
            elif error_logged.startswith("SymExec"):
              error_class = "Symbolic execution failed"
            else:
              error_class = "Other errors"
          
          error_dict[error_class] += 1
    
    error_dict_parsed = [{'Evaluation status': k, 'Count': v} for (k, v) in error_dict.items()]
    
    error_df = pd.DataFrame.from_records(error_dict_parsed)

    fig = px.bar(error_df, x='Evaluation status', y='Count')
    fig.update_layout(
        autosize=False,
        width=600,
        height=400,
        margin=dict(l=0, r=0, t=0, b=0)
      )
    fig.write_html(f"eval/plots/eval_errors.html")
    
  def version_parse(self):
    contract_directory = 'eval/contracts'
    version_dict = dict()
    
    (contracts_list, _) = read_file("contracts.json")
    
    contract_to_version_map = {current_contract_json['address']: current_contract_json['compiler'] for current_contract_json in contracts_list}
    
    for filename in os.listdir(contract_directory):
      full_filename = os.path.join(contract_directory, filename)
      # checking if it is a file
      if os.path.isfile(full_filename):
        with open(full_filename) as f:
          json_content = ast.literal_eval(f.read())
          
          if (json_content["status"] == 1):
            contract_address = filename[:-4]
            
            compiler_version_str = contract_to_version_map[contract_address]
            if compiler_version_str.startswith('v'):
              compiler_version_str = compiler_version_str[1:]
              
            compiler_version = version.parse(compiler_version_str)
            
            solidity_version_key = f'0.{compiler_version.minor}.x'
            
            if solidity_version_key not in version_dict:
              version_dict[solidity_version_key] = 0
          
            version_dict[solidity_version_key] += 1
    
    version_dict_parsed = [{'Solidity version': k, 'Count': v} for (k, v) in version_dict.items()]
    
    version_df = pd.DataFrame.from_records(version_dict_parsed)

    fig = px.bar(version_df, x='Solidity version', y='Count')
    fig.update_layout(
        autosize=False,
        width=600,
        height=400,
        margin=dict(l=0, r=0, t=0, b=0)
      )
    fig.write_html(f"eval/plots/eval_versions.html")
    
    
  def gas_parse(self):
    contract_directory = 'eval/contracts/v2'
    gas_dict = dict()
    for filename in os.listdir(contract_directory):
      full_filename = os.path.join(contract_directory, filename)
      # checking if it is a file
      if os.path.isfile(full_filename):
        with open(full_filename) as f:
          json_content = ast.literal_eval(f.read())
          if (json_content["status"] == 1):
            gas_classes = json_content["result"]["gas_class"]
            for gas_class, summary in gas_classes.items():
              if gas_class not in gas_dict:
                gas_dict[gas_class] = []
              gas_dict[gas_class].append(summary["sum"] / summary["count"] * 100)
            
    colors = n_colors('rgb(5, 200, 200)', 'rgb(200, 10, 10)', len(gas_dict), colortype='rgb')

    layout = go.Layout(
        autosize=False,
        width=800,
        height=400,
    )

    fig = go.Figure(layout = layout)
    for index, gas_class in enumerate(sorted(gas_dict)):
        print(f'Gas class {gas_class}: {len(gas_dict[gas_class])}')
        gas_df = pd.Series(gas_dict[gas_class], copy=False)
        fig.add_trace(go.Violin(x=gas_df, name=get_gas_class_name(gas_class), line_color=colors[index], spanmode="hard", box_visible=True, meanline_visible=True))

    fig.update_traces(orientation='h', side='positive', width=3, points=False)
    fig.update_layout(xaxis_showgrid=False, xaxis_zeroline=False, margin=dict(l=0, r=0, t=0, b=0))
    fig.write_html(f"eval/plots/gas_against_accuracy_plot.html")
    
  def exec_parse(self):
    mode_table = {
      ResultMode.default: self.default_parse,
      ResultMode.gas: self.gas_parse,
      ResultMode.coverage: self.coverage_parse,
      ResultMode.errors: self.error_parse,
      ResultMode.version: self.version_parse
    }
    mode_table[self.mode]()
    
def run_main(args):
  test_wrapper = EvalWrapper()
  test_wrapper.exec_eval_symloaded()

def eval_main(args):
  result_parser = ResultParser(args.mode)
  result_parser.exec_parse()

# if __name__ == "__main__":
#   # test_wrapper = EvalWrapper()
#   # test_wrapper.exec_eval()
  
#   result_parser = ResultParser()
#   result_parser.exec_parse()


############ PARSER #############

parser = argparse.ArgumentParser(description='Evaluate the symbolic execution engine using concrete transactions')
subparsers = parser.add_subparsers()

# Create a run subcommand    
parser_run = subparsers.add_parser('run', help='Run symbolic execution on verified contracts')
parser_run.set_defaults(func=run_main)

# Create a eval subcommand       
parser_eval = subparsers.add_parser('eval', help='Evaluate the completed symbolic execution results')
parser_eval.add_argument('mode', type=ResultMode, choices=list(ResultMode))
parser_eval.set_defaults(func=eval_main)

if len(sys.argv) <= 1:
    sys.argv.append('--help')

args = parser.parse_args()

# Run the appropriate function
args.func(args)
