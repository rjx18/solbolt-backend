import logging
import json
import os
import sys
import re
import time

from mythril.mythril import MythrilAnalyzer, MythrilDisassembler, MythrilConfig
from mythril.exceptions import (
    DetectorNotFoundError,
    CriticalError,
)
from mythril.analysis.symbolic import SymExecWrapper
from mythril.support.loader import DynLoader
from jinja2 import Environment, PackageLoader, select_autoescape
from mythril.laser.ethereum.svm import NodeFlags
from mythril.laser.smt import simplify
from z3 import Z3Exception
from mythril.laser.plugin.plugins.plugin_annotations import (
    GasMeterItem
)

default_colors = [
    {
        "border": "#26996f",
        "background": "#2f7e5b",
        "highlight": {"border": "#26996f", "background": "#28a16f"},
    },
    {
        "border": "#9e42b3",
        "background": "#842899",
        "highlight": {"border": "#9e42b3", "background": "#933da6"},
    },
    {
        "border": "#b82323",
        "background": "#991d1d",
        "highlight": {"border": "#b82323", "background": "#a61f1f"},
    },
    {
        "border": "#4753bf",
        "background": "#3b46a1",
        "highlight": {"border": "#4753bf", "background": "#424db3"},
    },
    {
        "border": "#26996f",
        "background": "#2f7e5b",
        "highlight": {"border": "#26996f", "background": "#28a16f"},
    },
    {
        "border": "#9e42b3",
        "background": "#842899",
        "highlight": {"border": "#9e42b3", "background": "#933da6"},
    },
    {
        "border": "#b82323",
        "background": "#991d1d",
        "highlight": {"border": "#b82323", "background": "#a61f1f"},
    },
    {
        "border": "#4753bf",
        "background": "#3b46a1",
        "highlight": {"border": "#4753bf", "background": "#424db3"},
    },
]

default_opts = {
    "autoResize": True,
    "height": "100%",
    "width": "100%",
    "manipulation": False,
    "layout": {
        "improvedLayout": True,
        "hierarchical": {
            "enabled": True,
            "levelSeparation": 450,
            "nodeSpacing": 200,
            "treeSpacing": 100,
            "blockShifting": True,
            "edgeMinimization": True,
            "parentCentralization": False,
            "direction": "LR",
            "sortMethod": "directed",
        },
    },
    "nodes": {
        "color": "#000000",
        "borderWidth": 1,
        "borderWidthSelected": 2,
        "chosen": True,
        "shape": "box",
        "font": {"align": "left", "color": "#FFFFFF"},
    },
    "edges": {
        "font": {
            "color": "#FFFFFF",
            "face": "arial",
            "background": "none",
            "strokeWidth": 0,
            "strokeColor": "#ffffff",
            "align": "horizontal",
            "multi": False,
            "vadjust": 0,
        }
    },
    "physics": {"enabled": False},
}

log = logging.getLogger(__name__)

# EXECUTION_TIMEOUT = int(os.environ.get("SOLBOLT_SYMEXEC_TIMEOUT", "300"))
EXECUTION_TIMEOUT = 300
# CREATION_TIMEOUT = int(os.environ.get("SOLBOLT_CREATION_TIMEOUT", "60"))
CREATION_TIMEOUT = 60

def merge_gas_items(global_gas_item, add_gas_item):
    global_gas_item.min_opcode_gas_used += add_gas_item.min_opcode_gas_used
    global_gas_item.max_opcode_gas_used += add_gas_item.max_opcode_gas_used
    global_gas_item.mem_gas_used += add_gas_item.mem_gas_used
    global_gas_item.min_storage_gas_used += add_gas_item.min_storage_gas_used
    global_gas_item.max_storage_gas_used += add_gas_item.max_storage_gas_used
    
    global_gas_item.num_invocations += add_gas_item.num_invocations
    global_gas_item.num_tx = max(global_gas_item.num_tx, add_gas_item.num_tx)

class SymExec:
    def __init__(self, 
                command = "analyze",
                solidity_files=None,
                onchain_address=None,
                contract_name=None,
                code=None,
                json=None,
                max_depth=128,
                call_depth_limit=10,
                strategy='bfs',
                loop_bound=10,
                transaction_count=2,
                execution_timeout=EXECUTION_TIMEOUT,
                solver_timeout=10000,
                create_timeout=CREATION_TIMEOUT,
                unconstrained_storage=False,
                bin_runtime=True,
                no_onchain_data=True,
                query_signature=None,
                ignore_constraints=True
                ) -> None:
        self.command = command
        self.solidity_files = solidity_files
        self.onchain_address = onchain_address
        self.contract_name = contract_name
        self.code = code
        self.json = json
        self.max_depth = max_depth
        self.call_depth_limit = call_depth_limit
        self.strategy = strategy
        self.loop_bound = loop_bound
        self.transaction_count = transaction_count
        self.execution_timeout = execution_timeout
        self.solver_timeout = solver_timeout
        self.create_timeout = create_timeout
        self.unconstrained_storage = unconstrained_storage
        self.bin_runtime = bin_runtime
        self.ignore_constraints = ignore_constraints
        
        self.infura_id = os.environ.get('SOLBOLT_INFURA_ID', '')
        self.no_onchain_data = no_onchain_data
        
        config = self.set_config()
        self.query_signature = query_signature
        solc_json = None
        solv = None
        self.disassembler = MythrilDisassembler(
            eth=config.eth,
            solc_version=solv,
            solc_settings_json=solc_json,
            enable_online_lookup=query_signature,
        )

        self.address = self.load_code(self.disassembler)
        
        # initialised with execute_command
        self.sym = None
        self.analyzer = None

    def set_config(self):
        config = MythrilConfig()
        if self.infura_id:
            config.set_api_infura_id(self.infura_id)
        if not self.no_onchain_data:
            config.set_api_from_config_path()

        return config

    def load_code(self, disassembler):
        address = None
        if self.code is not None:
            # Load from bytecode
            code = self.code[2:] if self.code.startswith("0x") else self.code
            address, _ = disassembler.load_from_bytecode(code, self.bin_runtime)
        elif self.solidity_files is not None and self.json is not None:
            # Compile Solidity source file(s)
            if len(self.json) > 1:
                self.exit_with_error(
                    "text",
                    "Cannot generate call graphs from multiple input files. Please do it one at a time.",
                )
            address, _ = disassembler.load_from_solidity_json(
                self.json,
                self.solidity_files,
                self.onchain_address,
                self.contract_name
            )  # list of files
        # elif self.solidity_files is not None:
        #     # Compile Solidity source file(s)
        #     if len(self.solidity_files) > 1:
        #         self.exit_with_error(
        #             "text",
        #             "Cannot generate call graphs from multiple input files. Please do it one at a time.",
        #         )
        #     address, _ = disassembler.load_from_solidity(
        #         self.solidity_files
        #     )  # list of files
        else:
            self.exit_with_error(
                "text",
                "No input bytecode. Please provide EVM code via -c BYTECODE, -a ADDRESS, -f BYTECODE_FILE or <SOLIDITY_FILE>",
            )
        return address

    def exit_with_error(self, format_, message):
        """
        Exits with error
        :param format_: The format of the message
        :param message: message
        """
        if format_ == "text" or format_ == "markdown":
            log.error(message)
        elif format_ == "json":
            result = {"success": False, "error": str(message), "issues": []}
        else:
            result = [
                {
                    "issues": [],
                    "sourceType": "",
                    "sourceFormat": "",
                    "sourceList": [],
                    "meta": {"logs": [{"level": "error", "hidden": True, "msg": message}]},
                }
            ]
        sys.exit()

    def execute_command(self):
        """
        Execute command
        :return:
        """

        start = time.process_time()

        self.analyzer = MythrilAnalyzer(
            strategy=self.strategy,
            disassembler=self.disassembler,
            address=self.address,
            max_depth=self.max_depth,
            execution_timeout=self.execution_timeout,
            loop_bound=self.loop_bound,
            create_timeout=self.create_timeout,
            # enable_iprof=self.enable_iprof,
            # disable_dependency_pruning=self.disable_dependency_pruning,
            use_onchain_data=not self.no_onchain_data,
            solver_timeout=self.solver_timeout,
            # parallel_solving=True,
            # custom_modules_directory=self.custom_modules_directory
            # if self.custom_modules_directory
            # else "",
            call_depth_limit=self.call_depth_limit,
            # sparse_pruning=self.sparse_pruning,
            unconstrained_storage=self.unconstrained_storage,
            ignore_constraints=self.ignore_constraints
            # solver_log=self.solver_log,
        )

        if not self.disassembler.contracts:
            self.exit_with_error(
                "text", "input files do not contain any valid contracts"
            )
            
        sym_contract = None 
        
        for analyzer_contract in self.analyzer.contracts:
            if (analyzer_contract.name == self.contract_name):
                sym_contract = analyzer_contract
                break
               
        if sym_contract is None:
            self.exit_with_error(
                "text", "contract name is not found within compiled contracts"
            )

        sym = SymExecWrapper(
                sym_contract, # here is where we set which contract it is
                self.address,
                self.strategy,
                dynloader=DynLoader(self.analyzer.eth, active=not self.no_onchain_data),
                max_depth=self.max_depth,
                execution_timeout=self.execution_timeout,
                transaction_count=self.transaction_count,
                create_timeout=self.create_timeout,
                loop_bound=self.loop_bound,
                # disable_dependency_pruning=self.disable_dependency_pruning,
                run_analysis_modules=False,
                # custom_modules_directory=self.custom_modules_directory,
            )

        self.sym = sym

    def parse_exec_results(self):
        # parse creation transactions
        creation_transaction_gas_map = dict()
        creation_gas_meter = self.sym.plugin_loader.laser_plugin_instances["gas-meter"].creation_gas_meter
        
        self.accumulate_gas(creation_transaction_gas_map, creation_gas_meter)
        
        # parse runtime transactions
        runtime_transaction_gas_map = dict()
        runtime_gas_meter = self.sym.plugin_loader.laser_plugin_instances["gas-meter"].runtime_gas_meter
        
        self.accumulate_gas(runtime_transaction_gas_map, runtime_gas_meter)
        
        coverage_plugin = self.sym.plugin_loader.laser_plugin_instances["coverage"]
        
        code = next(reversed(coverage_plugin.coverage))
        code_cov = coverage_plugin.coverage[code]
                                            
        if sum(code_cov[1]) == 0 and code_cov[0] == 0:
            cov_percentage = 0
        else:
            cov_percentage = sum(code_cov[1]) / float(code_cov[0]) * 100
        
        detected_issues = dict()
        
        loop_mutations = self.sym.plugin_loader.laser_plugin_instances["loop-mutation-detector"].detected_keys
        
        for key in loop_mutations:
            if key not in detected_issues:
                detected_issues[key] = list()
                
            detected_issues[key].append('loop-mutation')
        
        return (
            creation_transaction_gas_map, 
            runtime_transaction_gas_map, 
            self.sym.plugin_loader.laser_plugin_instances["function-tracker"].function_gas_meter,
            self.sym.plugin_loader.laser_plugin_instances["loop-gas-meter"].global_loop_gas_meter,
            cov_percentage,
            detected_issues
        )


    def accumulate_gas(self, transaction_gas_map, gas_meter):
        instruction_keys = list(gas_meter.keys())
        
        for key in instruction_keys:
            gas_meter_item = gas_meter[key]
            
            if (key not in transaction_gas_map):
                transaction_gas_map[key] = GasMeterItem()
            
            global_gas_item = transaction_gas_map[key]
            
            merge_gas_items(global_gas_item, gas_meter_item)


