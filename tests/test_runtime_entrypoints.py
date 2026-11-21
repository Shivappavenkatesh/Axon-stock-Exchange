import importlib


package_runtime = importlib.import_module("axon_aone.main")
orchestration_runtime = importlib.import_module("axon_aone.orchestration.main")


def test_package_runtime_reexports_canonical_entrypoints():
    assert package_runtime.main is orchestration_runtime.main
    assert package_runtime.run_scheduled is orchestration_runtime.run_scheduled
    assert package_runtime.parse_runtime_args is orchestration_runtime.parse_runtime_args
    assert package_runtime.run_cli is orchestration_runtime.run_cli


def test_parse_runtime_args_uses_last_mode_flag_and_schedule_switch():
    assert orchestration_runtime.parse_runtime_args(["--schedule", "--angel-one"]) == (True, False)
    assert orchestration_runtime.parse_runtime_args(["--angel-one", "--mock"]) == (False, True)