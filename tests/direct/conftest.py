import json
import re
import pytest
from contextlib import contextmanager


class UserError(Exception):
    pass


class RevertExpectationContext:
    def __init__(self, expected_msg=""):
        self.expected_msg = expected_msg

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError(f"Expected revert with '{self.expected_msg}', but call succeeded.")
        err_str = str(exc_val)
        if self.expected_msg and self.expected_msg not in err_str:
            raise AssertionError(
                f"Expected revert containing '{self.expected_msg}', but got: {err_str}"
            )
        return True  # Suppress exception as expected


class MockDirectVM:
    def __init__(self):
        self.sender = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
        self.value = 0
        self.block_timestamp = 1770000000
        self.web_mocks = []
        self.llm_mocks = []

    def mock_web(self, pattern: str, response: dict):
        self.web_mocks.append((re.compile(pattern), response))

    def mock_llm(self, pattern: str, response: str):
        self.llm_mocks.append((re.compile(pattern), response))

    def get_web(self, url: str):
        for pat, resp in reversed(self.web_mocks):
            if pat.search(url):
                class WebResponse:
                    def __init__(self, d):
                        self.status = d.get("status", 200)
                        self.status_code = self.status
                        b = d.get("body", "")
                        self.body = b.encode("utf-8") if isinstance(b, str) else b
                return WebResponse(resp)
        raise RuntimeError(f"No mock_web matched URL: {url}")

    def exec_prompt(self, prompt: str, response_format="json"):
        for pat, resp in reversed(self.llm_mocks):
            if pat.search(prompt):
                if response_format == "json":
                    return json.loads(resp) if isinstance(resp, str) else resp
                return resp
        raise RuntimeError(f"No mock_llm matched Prompt: {prompt[:100]}...")

    def expect_revert(self, expected_msg=""):
        return RevertExpectationContext(expected_msg)


@pytest.fixture
def direct_vm():
    return MockDirectVM()


@pytest.fixture
def direct_alice():
    return "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


@pytest.fixture
def direct_bob():
    return "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"


@pytest.fixture
def direct_deploy(direct_vm):
    def _deploy(contract_path: str):
        # Dynamically load contract with mock genlayer runtime
        import importlib.util
        import sys
        import types

        # Create mock genlayer module
        mock_gl = types.ModuleType("genlayer")

        class Address(str):
            def __new__(cls, val):
                return super().__new__(cls, str(val).lower())

        class u256(int):
            pass

        class u32(int):
            pass

        class TreeMap(dict):
            pass

        def allow_storage(cls):
            return cls

        class VMModule:
            UserError = UserError
            class Result:
                pass
            class Return(Result):
                def __init__(self, calldata):
                    self.calldata = calldata

            @staticmethod
            def run_nondet_unsafe(leader_fn, validator_fn):
                lead_res = leader_fn()
                lead_return = VMModule.Return(lead_res)
                if not validator_fn(lead_return):
                    raise UserError("Validator equivalence check failed.")
                return lead_res

        class NonDetModule:
            class web:
                @staticmethod
                def get(url):
                    return direct_vm.get_web(url)

            @staticmethod
            def exec_prompt(prompt, response_format="json"):
                return direct_vm.exec_prompt(prompt, response_format=response_format)

        class MessageProxy:
            @property
            def sender_address(self):
                return Address(direct_vm.sender)

            @property
            def value(self):
                return u256(direct_vm.value)

            @property
            def block_timestamp(self):
                return u256(direct_vm.block_timestamp)

        class BlockProxy:
            @property
            def timestamp(self):
                return u256(direct_vm.block_timestamp)

        class EvmModule:
            @staticmethod
            def contract_interface(cls):
                class ContractCaller:
                    def __init__(self, addr):
                        self.addr = addr
                    def emit(self):
                        return self
                    def emit_transfer(self, value=0):
                        pass
                    def __getattr__(self, name):
                        def _call(*args, **kwargs):
                            pass
                        return _call
                return ContractCaller

        class PublicDecorator:
            class WriteDecorator:
                def __call__(self, fn):
                    return fn
                def payable(self, fn):
                    return fn
            class ViewDecorator:
                def __call__(self, fn):
                    return fn

            write = WriteDecorator()
            view = ViewDecorator()

        mock_gl.Address = Address
        mock_gl.u256 = u256
        mock_gl.u32 = u32
        mock_gl.TreeMap = TreeMap
        mock_gl.allow_storage = allow_storage
        mock_gl.Contract = object
        mock_gl.public = PublicDecorator()
        mock_gl.vm = VMModule()
        mock_gl.nondet = NonDetModule()
        mock_gl.evm = EvmModule()
        mock_gl.message = MessageProxy()
        mock_gl.block = BlockProxy()
        mock_gl.gl = mock_gl

        sys.modules["genlayer"] = mock_gl

        spec = importlib.util.spec_from_file_location("contract_mod", contract_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Instantiate contract class (AuraSlash or VeriModel)
        for attr_name in ["AuraSlash", "VeriModel", "VestingGate", "SentinAI", "VeritasCourt"]:
            if hasattr(mod, attr_name):
                contract_cls = getattr(mod, attr_name)
                instance = contract_cls()
                instance.agreements = {}
                instance.challenges = {}
                instance.vaults = {}
                instance.disputes = {}
                instance.schedules = {}
                instance.tranches = {}
                return instance

        raise RuntimeError("No recognized contract class found in " + contract_path)

    return _deploy
