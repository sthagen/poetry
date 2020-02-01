import os
import shutil
import sys

import pytest
import tomlkit

from clikit.io import NullIO

from poetry.factory import Factory
from poetry.semver import Version
from poetry.utils._compat import WINDOWS
from poetry.utils._compat import Path
from poetry.utils.env import EnvCommandError
from poetry.utils.env import EnvManager
from poetry.utils.env import NoCompatiblePythonVersionFound
from poetry.utils.env import VirtualEnv
from poetry.utils.toml_file import TomlFile


MINIMAL_SCRIPT = """\

print("Minimal Output"),
"""

# Script expected to fail.
ERRORING_SCRIPT = """\
import nullpackage

print("nullpackage loaded"),
"""


class MockVirtualEnv(VirtualEnv):
    def __init__(self, path, base=None, sys_path=None):
        super(MockVirtualEnv, self).__init__(path, base=base)

        self._sys_path = sys_path

    @property
    def sys_path(self):
        if self._sys_path is not None:
            return self._sys_path

        return super(MockVirtualEnv, self).sys_path


@pytest.fixture()
def poetry(config):
    poetry = Factory().create_poetry(
        Path(__file__).parent.parent / "fixtures" / "simple_project"
    )
    poetry.set_config(config)

    return poetry


@pytest.fixture()
def manager(poetry):
    return EnvManager(poetry)


@pytest.fixture
def tmp_venv(tmp_dir, manager):
    venv_path = Path(tmp_dir) / "venv"

    manager.build_venv(str(venv_path))

    venv = VirtualEnv(venv_path)
    yield venv

    shutil.rmtree(str(venv.path))


def test_virtualenvs_with_spaces_in_their_path_work_as_expected(tmp_dir, manager):
    venv_path = Path(tmp_dir) / "Virtual Env"

    manager.build_venv(str(venv_path))

    venv = VirtualEnv(venv_path)

    assert venv.run("python", "-V", shell=True).startswith("Python")


def test_env_get_in_project_venv(manager, poetry):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    (poetry.file.parent / ".venv").mkdir()

    venv = manager.get()

    assert venv.path == poetry.file.parent / ".venv"

    shutil.rmtree(str(venv.path))


def build_venv(path, executable=None):
    os.mkdir(path)


def remove_venv(path):
    shutil.rmtree(path)


def check_output_wrapper(version=Version.parse("3.7.1")):
    def check_output(cmd, *args, **kwargs):
        if "sys.version_info[:3]" in cmd:
            return version.text
        elif "sys.version_info[:2]" in cmd:
            return "{}.{}".format(version.major, version.minor)
        else:
            return str(Path("/prefix"))

    return check_output


def test_activate_activates_non_existing_virtualenv_no_envs_file(
    tmp_dir, manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(),
    )
    mocker.patch(
        "poetry.utils._compat.subprocess.Popen.communicate",
        side_effect=[("/prefix", None), ("/prefix", None)],
    )
    m = mocker.patch("poetry.utils.env.EnvManager.build_venv", side_effect=build_venv)

    env = manager.activate("python3.7", NullIO())
    venv_name = EnvManager.generate_env_name("simple-project", str(poetry.file.parent))

    m.assert_called_with(
        os.path.join(tmp_dir, "{}-py3.7".format(venv_name)), executable="python3.7"
    )

    envs_file = TomlFile(Path(tmp_dir) / "envs.toml")
    assert envs_file.exists()
    envs = envs_file.read()
    assert envs[venv_name]["minor"] == "3.7"
    assert envs[venv_name]["patch"] == "3.7.1"

    assert env.path == Path(tmp_dir) / "{}-py3.7".format(venv_name)
    assert env.base == Path("/prefix")


def test_activate_activates_existing_virtualenv_no_envs_file(
    tmp_dir, manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))

    os.mkdir(os.path.join(tmp_dir, "{}-py3.7".format(venv_name)))

    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(),
    )
    mocker.patch(
        "poetry.utils._compat.subprocess.Popen.communicate",
        side_effect=[("/prefix", None)],
    )
    m = mocker.patch("poetry.utils.env.EnvManager.build_venv", side_effect=build_venv)

    env = manager.activate("python3.7", NullIO())

    m.assert_not_called()

    envs_file = TomlFile(Path(tmp_dir) / "envs.toml")
    assert envs_file.exists()
    envs = envs_file.read()
    assert envs[venv_name]["minor"] == "3.7"
    assert envs[venv_name]["patch"] == "3.7.1"

    assert env.path == Path(tmp_dir) / "{}-py3.7".format(venv_name)
    assert env.base == Path("/prefix")


def test_activate_activates_same_virtualenv_with_envs_file(
    tmp_dir, manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))

    envs_file = TomlFile(Path(tmp_dir) / "envs.toml")
    doc = tomlkit.document()
    doc[venv_name] = {"minor": "3.7", "patch": "3.7.1"}
    envs_file.write(doc)

    os.mkdir(os.path.join(tmp_dir, "{}-py3.7".format(venv_name)))

    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(),
    )
    mocker.patch(
        "poetry.utils._compat.subprocess.Popen.communicate",
        side_effect=[("/prefix", None)],
    )
    m = mocker.patch("poetry.utils.env.EnvManager.create_venv")

    env = manager.activate("python3.7", NullIO())

    m.assert_not_called()

    assert envs_file.exists()
    envs = envs_file.read()
    assert envs[venv_name]["minor"] == "3.7"
    assert envs[venv_name]["patch"] == "3.7.1"

    assert env.path == Path(tmp_dir) / "{}-py3.7".format(venv_name)
    assert env.base == Path("/prefix")


def test_activate_activates_different_virtualenv_with_envs_file(
    tmp_dir, manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))
    envs_file = TomlFile(Path(tmp_dir) / "envs.toml")
    doc = tomlkit.document()
    doc[venv_name] = {"minor": "3.7", "patch": "3.7.1"}
    envs_file.write(doc)

    os.mkdir(os.path.join(tmp_dir, "{}-py3.7".format(venv_name)))

    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(Version.parse("3.6.6")),
    )
    mocker.patch(
        "poetry.utils._compat.subprocess.Popen.communicate",
        side_effect=[("/prefix", None), ("/prefix", None), ("/prefix", None)],
    )
    m = mocker.patch("poetry.utils.env.EnvManager.build_venv", side_effect=build_venv)

    env = manager.activate("python3.6", NullIO())

    m.assert_called_with(
        os.path.join(tmp_dir, "{}-py3.6".format(venv_name)), executable="python3.6"
    )

    assert envs_file.exists()
    envs = envs_file.read()
    assert envs[venv_name]["minor"] == "3.6"
    assert envs[venv_name]["patch"] == "3.6.6"

    assert env.path == Path(tmp_dir) / "{}-py3.6".format(venv_name)
    assert env.base == Path("/prefix")


def test_activate_activates_recreates_for_different_patch(
    tmp_dir, manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))
    envs_file = TomlFile(Path(tmp_dir) / "envs.toml")
    doc = tomlkit.document()
    doc[venv_name] = {"minor": "3.7", "patch": "3.7.0"}
    envs_file.write(doc)

    os.mkdir(os.path.join(tmp_dir, "{}-py3.7".format(venv_name)))

    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(),
    )
    mocker.patch(
        "poetry.utils._compat.subprocess.Popen.communicate",
        side_effect=[
            ("/prefix", None),
            ('{"version_info": [3, 7, 0]}', None),
            ("/prefix", None),
            ("/prefix", None),
            ("/prefix", None),
        ],
    )
    build_venv_m = mocker.patch(
        "poetry.utils.env.EnvManager.build_venv", side_effect=build_venv
    )
    remove_venv_m = mocker.patch(
        "poetry.utils.env.EnvManager.remove_venv", side_effect=remove_venv
    )

    env = manager.activate("python3.7", NullIO())

    build_venv_m.assert_called_with(
        os.path.join(tmp_dir, "{}-py3.7".format(venv_name)), executable="python3.7"
    )
    remove_venv_m.assert_called_with(
        os.path.join(tmp_dir, "{}-py3.7".format(venv_name))
    )

    assert envs_file.exists()
    envs = envs_file.read()
    assert envs[venv_name]["minor"] == "3.7"
    assert envs[venv_name]["patch"] == "3.7.1"

    assert env.path == Path(tmp_dir) / "{}-py3.7".format(venv_name)
    assert env.base == Path("/prefix")
    assert (Path(tmp_dir) / "{}-py3.7".format(venv_name)).exists()


def test_activate_does_not_recreate_when_switching_minor(
    tmp_dir, manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))
    envs_file = TomlFile(Path(tmp_dir) / "envs.toml")
    doc = tomlkit.document()
    doc[venv_name] = {"minor": "3.7", "patch": "3.7.0"}
    envs_file.write(doc)

    os.mkdir(os.path.join(tmp_dir, "{}-py3.7".format(venv_name)))
    os.mkdir(os.path.join(tmp_dir, "{}-py3.6".format(venv_name)))

    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(Version.parse("3.6.6")),
    )
    mocker.patch(
        "poetry.utils._compat.subprocess.Popen.communicate",
        side_effect=[("/prefix", None), ("/prefix", None), ("/prefix", None)],
    )
    build_venv_m = mocker.patch(
        "poetry.utils.env.EnvManager.build_venv", side_effect=build_venv
    )
    remove_venv_m = mocker.patch(
        "poetry.utils.env.EnvManager.remove_venv", side_effect=remove_venv
    )

    env = manager.activate("python3.6", NullIO())

    build_venv_m.assert_not_called()
    remove_venv_m.assert_not_called()

    assert envs_file.exists()
    envs = envs_file.read()
    assert envs[venv_name]["minor"] == "3.6"
    assert envs[venv_name]["patch"] == "3.6.6"

    assert env.path == Path(tmp_dir) / "{}-py3.6".format(venv_name)
    assert env.base == Path("/prefix")
    assert (Path(tmp_dir) / "{}-py3.6".format(venv_name)).exists()


def test_deactivate_non_activated_but_existing(
    tmp_dir, manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))

    (
        Path(tmp_dir)
        / "{}-py{}".format(venv_name, ".".join(str(c) for c in sys.version_info[:2]))
    ).mkdir()

    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(),
    )

    manager.deactivate(NullIO())
    env = manager.get()

    assert env.path == Path(tmp_dir) / "{}-py{}".format(
        venv_name, ".".join(str(c) for c in sys.version_info[:2])
    )
    assert Path("/prefix")


def test_deactivate_activated(tmp_dir, manager, poetry, config, mocker):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))
    version = Version.parse(".".join(str(c) for c in sys.version_info[:3]))
    other_version = Version.parse("3.4") if version.major == 2 else version.next_minor
    (
        Path(tmp_dir) / "{}-py{}.{}".format(venv_name, version.major, version.minor)
    ).mkdir()
    (
        Path(tmp_dir)
        / "{}-py{}.{}".format(venv_name, other_version.major, other_version.minor)
    ).mkdir()

    envs_file = TomlFile(Path(tmp_dir) / "envs.toml")
    doc = tomlkit.document()
    doc[venv_name] = {
        "minor": "{}.{}".format(other_version.major, other_version.minor),
        "patch": other_version.text,
    }
    envs_file.write(doc)

    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(),
    )

    manager.deactivate(NullIO())
    env = manager.get()

    assert env.path == Path(tmp_dir) / "{}-py{}.{}".format(
        venv_name, version.major, version.minor
    )
    assert Path("/prefix")

    envs = envs_file.read()
    assert len(envs) == 0


def test_get_prefers_explicitly_activated_virtualenvs_over_env_var(
    tmp_dir, manager, poetry, config, mocker
):
    os.environ["VIRTUAL_ENV"] = "/environment/prefix"

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))

    config.merge({"virtualenvs": {"path": str(tmp_dir)}})
    (Path(tmp_dir) / "{}-py3.7".format(venv_name)).mkdir()

    envs_file = TomlFile(Path(tmp_dir) / "envs.toml")
    doc = tomlkit.document()
    doc[venv_name] = {"minor": "3.7", "patch": "3.7.0"}
    envs_file.write(doc)

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(),
    )
    mocker.patch(
        "poetry.utils._compat.subprocess.Popen.communicate",
        side_effect=[("/prefix", None)],
    )

    env = manager.get()

    assert env.path == Path(tmp_dir) / "{}-py3.7".format(venv_name)
    assert env.base == Path("/prefix")


def test_list(tmp_dir, manager, poetry, config):
    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))
    (Path(tmp_dir) / "{}-py3.7".format(venv_name)).mkdir()
    (Path(tmp_dir) / "{}-py3.6".format(venv_name)).mkdir()

    venvs = manager.list()

    assert 2 == len(venvs)
    assert (Path(tmp_dir) / "{}-py3.6".format(venv_name)) == venvs[0].path
    assert (Path(tmp_dir) / "{}-py3.7".format(venv_name)) == venvs[1].path


def test_remove_by_python_version(tmp_dir, manager, poetry, config, mocker):
    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))
    (Path(tmp_dir) / "{}-py3.7".format(venv_name)).mkdir()
    (Path(tmp_dir) / "{}-py3.6".format(venv_name)).mkdir()

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(Version.parse("3.6.6")),
    )

    venv = manager.remove("3.6")

    assert (Path(tmp_dir) / "{}-py3.6".format(venv_name)) == venv.path
    assert not (Path(tmp_dir) / "{}-py3.6".format(venv_name)).exists()


def test_remove_by_name(tmp_dir, manager, poetry, config, mocker):
    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))
    (Path(tmp_dir) / "{}-py3.7".format(venv_name)).mkdir()
    (Path(tmp_dir) / "{}-py3.6".format(venv_name)).mkdir()

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(Version.parse("3.6.6")),
    )

    venv = manager.remove("{}-py3.6".format(venv_name))

    assert (Path(tmp_dir) / "{}-py3.6".format(venv_name)) == venv.path
    assert not (Path(tmp_dir) / "{}-py3.6".format(venv_name)).exists()


def test_remove_also_deactivates(tmp_dir, manager, poetry, config, mocker):
    config.merge({"virtualenvs": {"path": str(tmp_dir)}})

    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))
    (Path(tmp_dir) / "{}-py3.7".format(venv_name)).mkdir()
    (Path(tmp_dir) / "{}-py3.6".format(venv_name)).mkdir()

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(Version.parse("3.6.6")),
    )

    envs_file = TomlFile(Path(tmp_dir) / "envs.toml")
    doc = tomlkit.document()
    doc[venv_name] = {"minor": "3.6", "patch": "3.6.6"}
    envs_file.write(doc)

    venv = manager.remove("python3.6")

    assert (Path(tmp_dir) / "{}-py3.6".format(venv_name)) == venv.path
    assert not (Path(tmp_dir) / "{}-py3.6".format(venv_name)).exists()

    envs = envs_file.read()
    assert venv_name not in envs


def test_env_has_symlinks_on_nix(tmp_dir, tmp_venv):
    venv_available = False
    try:
        from venv import EnvBuilder  # noqa

        venv_available = True
    except ImportError:
        pass

    if os.name != "nt" and venv_available:
        assert os.path.islink(tmp_venv.python)


def test_run_with_input(tmp_dir, tmp_venv):
    result = tmp_venv.run("python", "-", input_=MINIMAL_SCRIPT)

    assert result == "Minimal Output" + os.linesep


def test_run_with_input_non_zero_return(tmp_dir, tmp_venv):

    with pytest.raises(EnvCommandError) as processError:
        # Test command that will return non-zero returncode.
        tmp_venv.run("python", "-", input_=ERRORING_SCRIPT)

    assert processError.value.e.returncode == 1


def test_create_venv_tries_to_find_a_compatible_python_executable_using_generic_ones_first(
    manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    poetry.package.python_versions = "^3.6"
    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))

    mocker.patch("sys.version_info", (2, 7, 16))
    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(Version.parse("3.7.5")),
    )
    m = mocker.patch(
        "poetry.utils.env.EnvManager.build_venv", side_effect=lambda *args, **kwargs: ""
    )

    manager.create_venv(NullIO())

    m.assert_called_with(
        str(Path("/foo/virtualenvs/{}-py3.7".format(venv_name))), executable="python3"
    )


def test_create_venv_tries_to_find_a_compatible_python_executable_using_specific_ones(
    manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    poetry.package.python_versions = "^3.6"
    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))

    mocker.patch("sys.version_info", (2, 7, 16))
    mocker.patch(
        "poetry.utils._compat.subprocess.check_output", side_effect=["3.5.3", "3.8.0"]
    )
    m = mocker.patch(
        "poetry.utils.env.EnvManager.build_venv", side_effect=lambda *args, **kwargs: ""
    )

    manager.create_venv(NullIO())

    m.assert_called_with(
        str(Path("/foo/virtualenvs/{}-py3.8".format(venv_name))), executable="python3.8"
    )


def test_create_venv_fails_if_no_compatible_python_version_could_be_found(
    manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    poetry.package.python_versions = "^4.8"

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output", side_effect=["", "", "", ""]
    )
    m = mocker.patch(
        "poetry.utils.env.EnvManager.build_venv", side_effect=lambda *args, **kwargs: ""
    )

    with pytest.raises(NoCompatiblePythonVersionFound) as e:
        manager.create_venv(NullIO())

    expected_message = (
        "Poetry was unable to find a compatible version. "
        "If you have one, you can explicitly use it "
        'via the "env use" command.'
    )

    assert expected_message == str(e.value)
    assert 0 == m.call_count


def test_create_venv_does_not_try_to_find_compatible_versions_with_executable(
    manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    poetry.package.python_versions = "^4.8"

    mocker.patch("poetry.utils._compat.subprocess.check_output", side_effect=["3.8.0"])
    m = mocker.patch(
        "poetry.utils.env.EnvManager.build_venv", side_effect=lambda *args, **kwargs: ""
    )

    with pytest.raises(NoCompatiblePythonVersionFound) as e:
        manager.create_venv(NullIO(), executable="3.8")

    expected_message = (
        "The specified Python version (3.8.0) is not supported by the project (^4.8).\n"
        "Please choose a compatible version or loosen the python constraint "
        "specified in the pyproject.toml file."
    )

    assert expected_message == str(e.value)
    assert 0 == m.call_count


def test_create_venv_uses_patch_version_to_detect_compatibility(
    manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    version = Version.parse(".".join(str(c) for c in sys.version_info[:3]))
    poetry.package.python_versions = "^{}".format(
        ".".join(str(c) for c in sys.version_info[:3])
    )
    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))

    mocker.patch("sys.version_info", (version.major, version.minor, version.patch + 1))
    check_output = mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(Version.parse("3.6.9")),
    )
    m = mocker.patch(
        "poetry.utils.env.EnvManager.build_venv", side_effect=lambda *args, **kwargs: ""
    )

    manager.create_venv(NullIO())

    assert not check_output.called
    m.assert_called_with(
        str(
            Path(
                "/foo/virtualenvs/{}-py{}.{}".format(
                    venv_name, version.major, version.minor
                )
            )
        ),
        executable=None,
    )


def test_create_venv_uses_patch_version_to_detect_compatibility_with_executable(
    manager, poetry, config, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    version = Version.parse(".".join(str(c) for c in sys.version_info[:3]))
    poetry.package.python_versions = "~{}".format(
        ".".join(str(c) for c in (version.major, version.minor - 1, 0))
    )
    venv_name = manager.generate_env_name("simple-project", str(poetry.file.parent))

    check_output = mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(
            Version.parse("{}.{}.0".format(version.major, version.minor - 1))
        ),
    )
    m = mocker.patch(
        "poetry.utils.env.EnvManager.build_venv", side_effect=lambda *args, **kwargs: ""
    )

    manager.create_venv(
        NullIO(), executable="python{}.{}".format(version.major, version.minor - 1)
    )

    assert check_output.called
    m.assert_called_with(
        str(
            Path(
                "/foo/virtualenvs/{}-py{}.{}".format(
                    venv_name, version.major, version.minor - 1
                )
            )
        ),
        executable="python{}.{}".format(version.major, version.minor - 1),
    )


def test_activate_with_in_project_setting_does_not_fail_if_no_venvs_dir(
    manager, poetry, config, tmp_dir, mocker
):
    if "VIRTUAL_ENV" in os.environ:
        del os.environ["VIRTUAL_ENV"]

    config.merge(
        {
            "virtualenvs": {
                "path": str(Path(tmp_dir) / "virtualenvs"),
                "in-project": True,
            }
        }
    )

    mocker.patch(
        "poetry.utils._compat.subprocess.check_output",
        side_effect=check_output_wrapper(),
    )
    mocker.patch(
        "poetry.utils._compat.subprocess.Popen.communicate",
        side_effect=[("/prefix", None), ("/prefix", None)],
    )
    m = mocker.patch("poetry.utils.env.EnvManager.build_venv")

    manager.activate("python3.7", NullIO())

    m.assert_called_with(
        os.path.join(str(poetry.file.parent), ".venv"), executable="python3.7"
    )

    envs_file = TomlFile(Path(tmp_dir) / "virtualenvs" / "envs.toml")
    assert not envs_file.exists()


def test_env_site_packages_should_find_the_site_packages_directory_if_standard(tmp_dir):
    if WINDOWS:
        site_packages = Path(tmp_dir).joinpath("Lib/site-packages")
    else:
        site_packages = Path(tmp_dir).joinpath(
            "lib/python{}/site-packages".format(
                ".".join(str(v) for v in sys.version_info[:2])
            )
        )

    site_packages.mkdir(parents=True)

    env = MockVirtualEnv(Path(tmp_dir), Path(tmp_dir), sys_path=[str(site_packages)])

    assert site_packages == env.site_packages


def test_env_site_packages_should_find_the_site_packages_directory_if_root(tmp_dir):
    site_packages = Path(tmp_dir).joinpath("site-packages")
    site_packages.mkdir(parents=True)

    env = MockVirtualEnv(Path(tmp_dir), Path(tmp_dir), sys_path=[str(site_packages)])

    assert site_packages == env.site_packages


def test_env_site_packages_should_find_the_dist_packages_directory_if_necessary(
    tmp_dir,
):
    site_packages = Path(tmp_dir).joinpath("dist-packages")
    site_packages.mkdir(parents=True)

    env = MockVirtualEnv(Path(tmp_dir), Path(tmp_dir), sys_path=[str(site_packages)])

    assert site_packages == env.site_packages


def test_env_site_packages_should_prefer_site_packages_over_dist_packages(tmp_dir):
    dist_packages = Path(tmp_dir).joinpath("dist-packages")
    dist_packages.mkdir(parents=True)
    site_packages = Path(tmp_dir).joinpath("site-packages")
    site_packages.mkdir(parents=True)

    env = MockVirtualEnv(
        Path(tmp_dir), Path(tmp_dir), sys_path=[str(dist_packages), str(site_packages)]
    )

    assert site_packages == env.site_packages


def test_env_site_packages_should_raise_an_error_if_no_site_packages(tmp_dir):
    env = MockVirtualEnv(Path(tmp_dir), Path(tmp_dir), sys_path=[])

    with pytest.raises(RuntimeError):
        env.site_packages
