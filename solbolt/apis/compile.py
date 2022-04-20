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
            sol_files = request.json['files']
            settings = request.json['settings']
            
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

if __name__ == "__main__":
    
    
    
    sources = {
            'TREA.sol': {
                    'content': '''// SPDX-License-Identifier: MIT

pragma solidity ^0.8.0;

/// @title: Treasuring
/// @author: manifold.xyz

import "./ERC1155Creator.sol";

////////////////////////////////////////////////////////////////
//                                                            //
//                                                            //
//                                                            //
//       _____  .__                .____              .___    //
//      /     \ |__| ______ ______ |    |    ____   __| _/    //
//     /  \ /  \|  |/  ___//  ___/ |    |  _/ __ \ / __ |     //
//    /    Y    \  |\___ \ \___ \  |    |__\  ___// /_/ |     //
//    \____|__  /__/____  >____  > |_______ \___  >____ |     //
//            \/        \/     \/          \/   \/     \/     //
//                                                            //
//                                                            //
////////////////////////////////////////////////////////////////


contract TREA is ERC1155Creator {
    constructor() ERC1155Creator() {}
}'''
                },
                'ERC1155Creator.sol': {
                    'content': '''// SPDX-License-Identifier: MIT

pragma solidity ^0.8.0;

/// @author: manifold.xyz

import "@openzeppelin/contracts/proxy/Proxy.sol";
import "@openzeppelin/contracts/utils/Address.sol";
import "@openzeppelin/contracts/utils/StorageSlot.sol";

contract ERC1155Creator is Proxy {

    constructor() {
        assert(_IMPLEMENTATION_SLOT == bytes32(uint256(keccak256("eip1967.proxy.implementation")) - 1));
        StorageSlot.getAddressSlot(_IMPLEMENTATION_SLOT).value = 0x142FD5b9d67721EfDA3A5E2E9be47A96c9B724A4;
        Address.functionDelegateCall(
            0x142FD5b9d67721EfDA3A5E2E9be47A96c9B724A4,
            abi.encodeWithSignature("initialize()")
        );
    }

    /**
     * @dev Storage slot with the address of the current implementation.
     * This is the keccak-256 hash of "eip1967.proxy.implementation" subtracted by 1, and is
     * validated in the constructor.
     */
    bytes32 internal constant _IMPLEMENTATION_SLOT = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    /**
     * @dev Returns the current implementation address.
     */
     function implementation() public view returns (address) {
        return _implementation();
    }

    function _implementation() internal override view returns (address) {
        return StorageSlot.getAddressSlot(_IMPLEMENTATION_SLOT).value;
    }    

}'''
                },
                '@openzeppelin/contracts/proxy/Proxy.sol': {
                    'content': '''// SPDX-License-Identifier: MIT
// OpenZeppelin Contracts (last updated v4.5.0) (proxy/Proxy.sol)

pragma solidity ^0.8.0;

/**
 * @dev This abstract contract provides a fallback function that delegates all calls to another contract using the EVM
 * instruction `delegatecall`. We refer to the second contract as the _implementation_ behind the proxy, and it has to
 * be specified by overriding the virtual {_implementation} function.
 *
 * Additionally, delegation to the implementation can be triggered manually through the {_fallback} function, or to a
 * different contract through the {_delegate} function.
 *
 * The success and return data of the delegated call will be returned back to the caller of the proxy.
 */
abstract contract Proxy {
    /**
     * @dev Delegates the current call to `implementation`.
     *
     * This function does not return to its internal call site, it will return directly to the external caller.
     */
    function _delegate(address implementation) internal virtual {
        assembly {
            // Copy msg.data. We take full control of memory in this inline assembly
            // block because it will not return to Solidity code. We overwrite the
            // Solidity scratch pad at memory position 0.
            calldatacopy(0, 0, calldatasize())

            // Call the implementation.
            // out and outsize are 0 because we don't know the size yet.
            let result := delegatecall(gas(), implementation, 0, calldatasize(), 0, 0)

            // Copy the returned data.
            returndatacopy(0, 0, returndatasize())

            switch result
            // delegatecall returns 0 on error.
            case 0 {
                revert(0, returndatasize())
            }
            default {
                return(0, returndatasize())
            }
        }
    }

    /**
     * @dev This is a virtual function that should be overriden so it returns the address to which the fallback function
     * and {_fallback} should delegate.
     */
    function _implementation() internal view virtual returns (address);

    /**
     * @dev Delegates the current call to the address returned by `_implementation()`.
     *
     * This function does not return to its internall call site, it will return directly to the external caller.
     */
    function _fallback() internal virtual {
        _beforeFallback();
        _delegate(_implementation());
    }

    /**
     * @dev Fallback function that delegates calls to the address returned by `_implementation()`. Will run if no other
     * function in the contract matches the call data.
     */
    fallback() external payable virtual {
        _fallback();
    }

    /**
     * @dev Fallback function that delegates calls to the address returned by `_implementation()`. Will run if call data
     * is empty.
     */
    receive() external payable virtual {
        _fallback();
    }

    /**
     * @dev Hook that is called before falling back to the implementation. Can happen as part of a manual `_fallback`
     * call, or as part of the Solidity `fallback` or `receive` functions.
     *
     * If overriden should call `super._beforeFallback()`.
     */
    function _beforeFallback() internal virtual {}
}'''
                },
                '@openzeppelin/contracts/utils/Address.sol': {
                    'content': '''// SPDX-License-Identifier: MIT
// OpenZeppelin Contracts (last updated v4.5.0) (utils/Address.sol)

pragma solidity ^0.8.1;

/**
 * @dev Collection of functions related to the address type
 */
library Address {
    /**
     * @dev Returns true if `account` is a contract.
     *
     * [IMPORTANT]
     * ====
     * It is unsafe to assume that an address for which this function returns
     * false is an externally-owned account (EOA) and not a contract.
     *
     * Among others, `isContract` will return false for the following
     * types of addresses:
     *
     *  - an externally-owned account
     *  - a contract in construction
     *  - an address where a contract will be created
     *  - an address where a contract lived, but was destroyed
     * ====
     *
     * [IMPORTANT]
     * ====
     * You shouldn't rely on `isContract` to protect against flash loan attacks!
     *
     * Preventing calls from contracts is highly discouraged. It breaks composability, breaks support for smart wallets
     * like Gnosis Safe, and does not provide security since it can be circumvented by calling from a contract
     * constructor.
     * ====
     */
    function isContract(address account) internal view returns (bool) {
        // This method relies on extcodesize/address.code.length, which returns 0
        // for contracts in construction, since the code is only stored at the end
        // of the constructor execution.

        return account.code.length > 0;
    }

    /**
     * @dev Replacement for Solidity's `transfer`: sends `amount` wei to
     * `recipient`, forwarding all available gas and reverting on errors.
     *
     * https://eips.ethereum.org/EIPS/eip-1884[EIP1884] increases the gas cost
     * of certain opcodes, possibly making contracts go over the 2300 gas limit
     * imposed by `transfer`, making them unable to receive funds via
     * `transfer`. {sendValue} removes this limitation.
     *
     * https://diligence.consensys.net/posts/2019/09/stop-using-soliditys-transfer-now/[Learn more].
     *
     * IMPORTANT: because control is transferred to `recipient`, care must be
     * taken to not create reentrancy vulnerabilities. Consider using
     * {ReentrancyGuard} or the
     * https://solidity.readthedocs.io/en/v0.5.11/security-considerations.html#use-the-checks-effects-interactions-pattern[checks-effects-interactions pattern].
     */
    function sendValue(address payable recipient, uint256 amount) internal {
        require(address(this).balance >= amount, "Address: insufficient balance");

        (bool success, ) = recipient.call{value: amount}("");
        require(success, "Address: unable to send value, recipient may have reverted");
    }

    /**
     * @dev Performs a Solidity function call using a low level `call`. A
     * plain `call` is an unsafe replacement for a function call: use this
     * function instead.
     *
     * If `target` reverts with a revert reason, it is bubbled up by this
     * function (like regular Solidity function calls).
     *
     * Returns the raw returned data. To convert to the expected return value,
     * use https://solidity.readthedocs.io/en/latest/units-and-global-variables.html?highlight=abi.decode#abi-encoding-and-decoding-functions[`abi.decode`].
     *
     * Requirements:
     *
     * - `target` must be a contract.
     * - calling `target` with `data` must not revert.
     *
     * _Available since v3.1._
     */
    function functionCall(address target, bytes memory data) internal returns (bytes memory) {
        return functionCall(target, data, "Address: low-level call failed");
    }

    /**
     * @dev Same as {xref-Address-functionCall-address-bytes-}[`functionCall`], but with
     * `errorMessage` as a fallback revert reason when `target` reverts.
     *
     * _Available since v3.1._
     */
    function functionCall(
        address target,
        bytes memory data,
        string memory errorMessage
    ) internal returns (bytes memory) {
        return functionCallWithValue(target, data, 0, errorMessage);
    }

    /**
     * @dev Same as {xref-Address-functionCall-address-bytes-}[`functionCall`],
     * but also transferring `value` wei to `target`.
     *
     * Requirements:
     *
     * - the calling contract must have an ETH balance of at least `value`.
     * - the called Solidity function must be `payable`.
     *
     * _Available since v3.1._
     */
    function functionCallWithValue(
        address target,
        bytes memory data,
        uint256 value
    ) internal returns (bytes memory) {
        return functionCallWithValue(target, data, value, "Address: low-level call with value failed");
    }

    /**
     * @dev Same as {xref-Address-functionCallWithValue-address-bytes-uint256-}[`functionCallWithValue`], but
     * with `errorMessage` as a fallback revert reason when `target` reverts.
     *
     * _Available since v3.1._
     */
    function functionCallWithValue(
        address target,
        bytes memory data,
        uint256 value,
        string memory errorMessage
    ) internal returns (bytes memory) {
        require(address(this).balance >= value, "Address: insufficient balance for call");
        require(isContract(target), "Address: call to non-contract");

        (bool success, bytes memory returndata) = target.call{value: value}(data);
        return verifyCallResult(success, returndata, errorMessage);
    }

    /**
     * @dev Same as {xref-Address-functionCall-address-bytes-}[`functionCall`],
     * but performing a static call.
     *
     * _Available since v3.3._
     */
    function functionStaticCall(address target, bytes memory data) internal view returns (bytes memory) {
        return functionStaticCall(target, data, "Address: low-level static call failed");
    }

    /**
     * @dev Same as {xref-Address-functionCall-address-bytes-string-}[`functionCall`],
     * but performing a static call.
     *
     * _Available since v3.3._
     */
    function functionStaticCall(
        address target,
        bytes memory data,
        string memory errorMessage
    ) internal view returns (bytes memory) {
        require(isContract(target), "Address: static call to non-contract");

        (bool success, bytes memory returndata) = target.staticcall(data);
        return verifyCallResult(success, returndata, errorMessage);
    }

    /**
     * @dev Same as {xref-Address-functionCall-address-bytes-}[`functionCall`],
     * but performing a delegate call.
     *
     * _Available since v3.4._
     */
    function functionDelegateCall(address target, bytes memory data) internal returns (bytes memory) {
        return functionDelegateCall(target, data, "Address: low-level delegate call failed");
    }

    /**
     * @dev Same as {xref-Address-functionCall-address-bytes-string-}[`functionCall`],
     * but performing a delegate call.
     *
     * _Available since v3.4._
     */
    function functionDelegateCall(
        address target,
        bytes memory data,
        string memory errorMessage
    ) internal returns (bytes memory) {
        require(isContract(target), "Address: delegate call to non-contract");

        (bool success, bytes memory returndata) = target.delegatecall(data);
        return verifyCallResult(success, returndata, errorMessage);
    }

    /**
     * @dev Tool to verifies that a low level call was successful, and revert if it wasn't, either by bubbling the
     * revert reason using the provided one.
     *
     * _Available since v4.3._
     */
    function verifyCallResult(
        bool success,
        bytes memory returndata,
        string memory errorMessage
    ) internal pure returns (bytes memory) {
        if (success) {
            return returndata;
        } else {
            // Look for revert reason and bubble it up if present
            if (returndata.length > 0) {
                // The easiest way to bubble the revert reason is using memory via assembly

                assembly {
                    let returndata_size := mload(returndata)
                    revert(add(32, returndata), returndata_size)
                }
            } else {
                revert(errorMessage);
            }
        }
    }
}'''
                },
                '@openzeppelin/contracts/utils/StorageSlot.sol': {
                    'content': '''// SPDX-License-Identifier: MIT
// OpenZeppelin Contracts v4.4.1 (utils/StorageSlot.sol)

pragma solidity ^0.8.0;

/**
 * @dev Library for reading and writing primitive types to specific storage slots.
 *
 * Storage slots are often used to avoid storage conflict when dealing with upgradeable contracts.
 * This library helps with reading and writing to such slots without the need for inline assembly.
 *
 * The functions in this library return Slot structs that contain a `value` member that can be used to read or write.
 *
 * Example usage to set ERC1967 implementation slot:
 * ```
 * contract ERC1967 {
 *     bytes32 internal constant _IMPLEMENTATION_SLOT = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;
 *
 *     function _getImplementation() internal view returns (address) {
 *         return StorageSlot.getAddressSlot(_IMPLEMENTATION_SLOT).value;
 *     }
 *
 *     function _setImplementation(address newImplementation) internal {
 *         require(Address.isContract(newImplementation), "ERC1967: new implementation is not a contract");
 *         StorageSlot.getAddressSlot(_IMPLEMENTATION_SLOT).value = newImplementation;
 *     }
 * }
 * ```
 *
 * _Available since v4.1 for `address`, `bool`, `bytes32`, and `uint256`._
 */
library StorageSlot {
    struct AddressSlot {
        address value;
    }

    struct BooleanSlot {
        bool value;
    }

    struct Bytes32Slot {
        bytes32 value;
    }

    struct Uint256Slot {
        uint256 value;
    }

    /**
     * @dev Returns an `AddressSlot` with member `value` located at `slot`.
     */
    function getAddressSlot(bytes32 slot) internal pure returns (AddressSlot storage r) {
        assembly {
            r.slot := slot
        }
    }

    /**
     * @dev Returns an `BooleanSlot` with member `value` located at `slot`.
     */
    function getBooleanSlot(bytes32 slot) internal pure returns (BooleanSlot storage r) {
        assembly {
            r.slot := slot
        }
    }

    /**
     * @dev Returns an `Bytes32Slot` with member `value` located at `slot`.
     */
    function getBytes32Slot(bytes32 slot) internal pure returns (Bytes32Slot storage r) {
        assembly {
            r.slot := slot
        }
    }

    /**
     * @dev Returns an `Uint256Slot` with member `value` located at `slot`.
     */
    function getUint256Slot(bytes32 slot) internal pure returns (Uint256Slot storage r) {
        assembly {
            r.slot := slot
        }
    }
}'''
                },
            }
    
    json_settings = {
            "optimizer": {
                        "enabled": True,
                        "runs": 300,
                    },
            "evmVersion": 'berlin',
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
    
    solc_binary = f"./solc/solc-linux-amd64-v0.8.7+commit.e28d00a7"
    
    result = get_solc_json(sources, json_settings, solc_binary)
    
    print(result)

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