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
                solidity_file_contents=None,
                onchain_address=None,
                code=None,
                json=None,
                max_depth=128,
                call_depth_limit=10,
                strategy='bfs',
                loop_bound=10,
                transaction_count=2,
                execution_timeout=120,
                solver_timeout=10000,
                create_timeout=10,
                unconstrained_storage=False,
                bin_runtime=True,
                infura_id=None,
                no_onchain_data=True,
                query_signature=None
                ) -> None:
        self.command = command
        self.solidity_files = solidity_files
        self.solidity_file_contents = solidity_file_contents
        self.onchain_address = onchain_address
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
        
        self.infura_id = infura_id
        self.no_onchain_data = no_onchain_data
        
        config = self.set_config()
        query_signature = query_signature
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
        elif self.solidity_files is not None and self.json is not None and self.solidity_file_contents is not None:
            # Compile Solidity source file(s)
            if len(self.json) > 1:
                self.exit_with_error(
                    "text",
                    "Cannot generate call graphs from multiple input files. Please do it one at a time.",
                )
            address, _ = disassembler.load_from_solidity_json(
                self.json,
                self.solidity_files,
                self.solidity_file_contents,
                self.onchain_address
            )  # list of files
        elif self.solidity_files is not None:
            # Compile Solidity source file(s)
            if len(self.solidity_files) > 1:
                self.exit_with_error(
                    "text",
                    "Cannot generate call graphs from multiple input files. Please do it one at a time.",
                )
            address, _ = disassembler.load_from_solidity(
                self.solidity_files
            )  # list of files
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
            print(json.dumps(result))
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
            print(json.dumps(result))
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
            # use_onchain_data=not self.no_onchain_data,
            solver_timeout=self.solver_timeout,
            # parallel_solving=True,
            # custom_modules_directory=self.custom_modules_directory
            # if self.custom_modules_directory
            # else "",
            call_depth_limit=self.call_depth_limit,
            # sparse_pruning=self.sparse_pruning,
            unconstrained_storage=self.unconstrained_storage,
            # solver_log=self.solver_log,
        )

        print(str(self.disassembler.contracts))

        if not self.disassembler.contracts:
            self.exit_with_error(
                "text", "input files do not contain any valid contracts"
            )

        sym = SymExecWrapper(
                self.analyzer.contracts[0], # here is where we set which contract it is
                self.address,
                self.strategy,
                # dynloader=DynLoader(self.eth, active=self.use_onchain_data),
                max_depth=self.max_depth,
                execution_timeout=self.execution_timeout,
                transaction_count=self.transaction_count,
                create_timeout=self.create_timeout,
                # disable_dependency_pruning=self.disable_dependency_pruning,
                run_analysis_modules=False,
                # custom_modules_directory=self.custom_modules_directory,
            )

        print("sym.py: Sym exec took : " + str(time.process_time() - start)  + "s")

        self.sym = sym

    def parse_exec_results(self):
        # parse creation transactions
        creation_transaction_gas_map = dict()
        creation_gas_meter = self.sym.plugin_loader.laser_plugin_instances["gas-meter"].creation_gas_meter
        
        self.accumulate_gas(creation_transaction_gas_map, creation_gas_meter, is_creation=True)
        
        # parse runtime transactions
        runtime_transaction_gas_map = dict()
        runtime_gas_meter = self.sym.plugin_loader.laser_plugin_instances["gas-meter"].runtime_gas_meter
        
        self.accumulate_gas(runtime_transaction_gas_map, runtime_gas_meter, is_creation=False)
        
        return (
            creation_transaction_gas_map, 
            runtime_transaction_gas_map, 
            self.sym.plugin_loader.laser_plugin_instances["function-tracker"].function_gas_meter,
            self.sym.plugin_loader.laser_plugin_instances["loop-gas-meter"].global_loop_gas_meter
        )
        


    def accumulate_gas(self, transaction_gas_map, gas_meter, is_creation=False):
        instruction_keys = list(gas_meter.keys())
        
        for key in instruction_keys:
            gas_meter_item = gas_meter[key]
            
            if (key not in transaction_gas_map):
                transaction_gas_map[key] = GasMeterItem()
            
            global_gas_item = transaction_gas_map[key]
            
            merge_gas_items(global_gas_item, gas_meter_item)


    def generate_graph(
        self,
        statespace,
        title="Mythril / Ethereum LASER Symbolic VM",
        physics=False,
        phrackify=False,
    ):
        """

        :param statespace:
        :param title:
        :param physics:
        :param phrackify:
        :return:
        """
        env = Environment(
            loader=PackageLoader("mythril.analysis"),
            autoescape=select_autoescape(["html", "xml"]),
        )
        template = env.get_template("callgraph.html")

        graph_opts = default_opts

        graph_opts["physics"]["enabled"] = physics

        return template.render(
            title=title,
            nodes=self.extract_nodes(statespace),
            edges=self.extract_edges(statespace),
            phrackify=phrackify,
            opts=graph_opts,
        )
        
    def extract_nodes(self, statespace):
        """

        :param statespace:
        :param color_map:
        :return:
        """
        nodes = []
        color_map = {}
        for node_key in statespace.nodes:
            node = statespace.nodes[node_key]
            instructions = [state.get_current_instruction() for state in node.states]
            code_split = []
            for instruction in instructions:
                if instruction["opcode"].startswith("PUSH"):
                    argument_to_append = ""
                    if isinstance(instruction["argument"], str):
                        argument_to_append = instruction["argument"]
                    else:
                        argument_to_append = "0x"
                        for word in instruction["argument"]:
                            argument_to_append += '{0:0{1}x}'.format(word,2)
                    code_line = "%d %s %s" % (
                        instruction["address"],
                        instruction["opcode"],
                        argument_to_append,
                    )
                elif (
                    instruction["opcode"].startswith("JUMPDEST")
                    and NodeFlags.FUNC_ENTRY in node.flags
                    and instruction["address"] == node.start_addr
                ):
                    code_line = node.function_name
                else:
                    code_line = "%d %s" % (instruction["address"], instruction["opcode"])

                code_line = re.sub(
                    "([0-9a-f]{8})[0-9a-f]+", lambda m: m.group(1) + "(...)", code_line
                )
                code_split.append(code_line)

            truncated_code = (
                "\n".join(code_split)
                if (len(code_split) < 7)
                else "\n".join(code_split[:6]) + "\n(click to expand +)"
            )

            if node.get_cfg_dict()["contract_name"] not in color_map.keys():
                color = default_colors[len(color_map) % len(default_colors)]
                color_map[node.get_cfg_dict()["contract_name"]] = color

            nodes.append(
                {
                    "id": str(node_key),
                    "color": color_map.get(
                        node.get_cfg_dict()["contract_name"], default_colors[0]
                    ),
                    "size": 150,
                    "fullLabel": "\n".join(code_split),
                    "label": truncated_code,
                    "truncLabel": truncated_code,
                    "isExpanded": False,
                }
            )
        return nodes


    def extract_edges(self, statespace):
        """

        :param statespace:
        :return:
        """
        edges = []
        for edge in statespace.edges:
            if edge.condition is None:
                label = ""
            else:
                try:
                    label = str(simplify(edge.condition)).replace("\n", "")
                except Z3Exception:
                    label = str(edge.condition).replace("\n", "")

            label = re.sub(
                r"([^_])([\d]{2}\d+)", lambda m: m.group(1) + hex(int(m.group(2))), label
            )

            edges.append(
                {
                    "from": str(edge.as_dict["from"]),
                    "to": str(edge.as_dict["to"]),
                    "arrows": "to",
                    "label": label,
                    "smooth": {"type": "cubicBezier"},
                }
            )
        return edges


if __name__ == "__main__":
    bytecode = "ffffffff16146107f0576040517f08c379a00000000000000000000000000000000000000000000000000000000081526004016107e790610f4a565b60405180910390fd5b600160008273ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002060010160009054906101000a900460ff1615610880576040517f08c379a000000000000000000000000000000000000000000000000000000000815260040161087790610fb6565b60405180910390fd5b6000600160008373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff16815260200190815260200160002060000154146108cf57600080fd5b60018060008373ffffffffffffffffffffffffffffffffffffffff1673ffffffffffffffffffffffffffffffffffffffff1681526020019081526020016000206000018190555050565b60016020528060005260406000206000915090508060000154908060010160009054906101000a900460ff16908060010160019054906101000a900473ffffffffffffffffffffffffffffffffffffffff16908060020154905084565b600060026109826106da565b8154811061099357610992610c97565b5b906000526020600020906002020160000154905090565b600080fd5b6000819050919050565b6109c2816109af565b81146109cd57600080fd5b50565b6000813590506109df816109b9565b92915050565b6000602082840312156109fb576109fa6109aa565b5b6000610a09848285016109d0565b91505092915050565b6000819050919050565b610a2581610a12565b82525050565b610a34816109af565b82525050565b6000604082019050610a4f6000830185610a1c565b610a5c6020830184610a2b565b9392505050565b600073ffffffffffffffffffffffffffffffffffffffff82169050919050565b6000610a8e82610a63565b9050919050565b610a9e81610a83565b82525050565b6000602082019050610ab96000830184610a95565b92915050565b610ac881610a83565b8114610ad357600080fd5b50565b600081359050610ae581610abf565b92915050565b600060208284031215610b0157610b006109aa565b5b6000610b0f84828501610ad6565b91505092915050565b6000602082019050610b2d6000830184610a2b565b92915050565b60008115159050919050565b610b4881610b33565b82525050565b6000608082019050610b636000830187610a2b565b610b706020830186610b3f565b610b7d6040830185610a95565b610b8a6060830184610a2b565b95945050505050565b6000602082019050610ba86000830184610a1c565b92915050565b600082825260208201905092915050565b7f486173206e6f20726967687420746f20766f7465000000000000000000000000600082015250565b6000610bf5601483610bae565b9150610c0082610bbf565b602082019050919050565b60006020820190508181036000830152610c2481610be8565b9050919050565b7f416c726561647920766f7465642e000000000000000000000000000000000000600082015250565b6000610c61600e83610bae565b9150610c6c82610c2b565b602082019050919050565b60006020820190508181036000830152610c9081610c54565b9050919050565b7f4e487b7100000000000000000000000000000000000000000000000000000000600052603260045260246000fd5b7f4e487b7100000000000000000000000000000000000000000000000000000000600052601160045260246000fd5b6000610d00826109af565b9150610d0b836109af565b9250827fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff03821115610d4057610d3f610cc6565b5b828201905092915050565b7f596f7520616c726561647920766f7465642e0000000000000000000000000000600082015250565b6000610d81601283610bae565b9150610d8c82610d4b565b602082019050919050565b60006020820190508181036000830152610db081610d74565b9050919050565b7f53656c662d64656c65676174696f6e20697320646973616c6c6f7765642e0000600082015250565b6000610ded601e83610bae565b9150610df882610db7565b602082019050919050565b60006020820190508181036000830152610e1c81610de0565b9050919050565b7f466f756e64206c6f6f7020696e2064656c65676174696f6e2e00000000000000600082015250565b6000610e59601983610bae565b9150610e6482610e23565b602082019050919050565b60006020820190508181036000830152610e8881610e4c565b9050919050565b6000610e9a826109af565b91507fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff821415610ecd57610ecc610cc6565b5b600182019050919050565b7f4f6e6c79206368616972706572736f6e2063616e20676976652072696768742060008201527f746f20766f74652e000000000000000000000000000000000000000000000000602082015250565b6000610f34602883610bae565b9150610f3f82610ed8565b604082019050919050565b60006020820190508181036000830152610f6381610f27565b9050919050565b7f54686520766f74657220616c726561647920766f7465642e0000000000000000600082015250565b6000610fa0601883610bae565b9150610fab82610f6a565b602082019050919050565b60006020820190508181036000830152610fcf81610f93565b905091905056fea26469706673582212209f6645214cc4dd0468f8baaa83397392bcb903ad226dff635184c53192e6543064736f6c637829302e382e31312d646576656c6f702e323032312e31322e31382b636f6d6d69742e3130323839666263005a"
    f = open('test.json')
    data = json.load(f)
    
    sol_file = open('test.sol', "r")
    sol_contents = sol_file.read()
    
    # exec_env = SymExec(solidity_files=["output.sol"], json=[data], solidity_file_contents=[sol_contents], transaction_count=3, execution_timeout=60, solver_timeout=20000, loop_bound=10)
    # exec_env = SymExec(solidity_files=["test.sol"])
    exec_env = SymExec(onchain_address="0x2C4e8f2D746113d0696cE89B35F0d8bF88E0AEcA", 
                       transaction_count=3, 
                       execution_timeout=60, 
                       solver_timeout=20000, 
                       loop_bound=10,
                       infura_id="2b46429217e54609bc4b918ea219e894",
                       no_onchain_data=False,
                       query_signature=True)
    exec_env.execute_command()
    
    (creation_transaction_gas_map, runtime_transaction_gas_map, function_gas_meter, loop_gas_meter) = exec_env.parse_exec_results()
    
    print(json.dumps({ k: v.to_json() for k, v in runtime_transaction_gas_map.items() }))
    
    # print(json.dumps({ k: v.to_json() for k, v in new_transaction_gas_map.items() }))
    
    print(function_gas_meter)
    
    print('Number of loops found: ' + str(len(loop_gas_meter.keys())))
    for key in loop_gas_meter.keys():
        print(f'LOOP GAS METER FOR {key}')
        
        key_gas_items = loop_gas_meter[key]
        
        for pc in key_gas_items.keys():
            loop_gas_item = key_gas_items[pc]
            if len(loop_gas_item.iteration_gas_cost) > 0:
                print(f'\tPC {pc}')
                print(f'\t\tis_hidden: {"Yes" if loop_gas_item.is_hidden else "No"}')
                print(f'\t\tAverage iteration cost: {sum(loop_gas_item.iteration_gas_cost) / len(loop_gas_item.iteration_gas_cost)}')
                print(f'\t\tNum iterations seen: {len(loop_gas_item.iteration_gas_cost)}')
            