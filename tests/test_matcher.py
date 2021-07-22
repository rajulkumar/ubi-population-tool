import pytest

from operator import attrgetter
from more_executors.futures import f_proxy, f_return
from pubtools.pulplib import (
    RpmUnit,
    Criteria,
    YumRepository,
    FakeController,
    ModulemdUnit,
)
from ubiconfig import UbiConfig

from ubipop._matcher import UbiUnit, Matcher, flatten_list_of_sets, ModularMatcher
from ubipop import RepoSet


@pytest.fixture(name="pulp")
def fake_pulp():
    yield FakeController()


@pytest.fixture(name="ubi_config")
def fake_ubi_config():
    config_dict = {
        "modules": {
            "include": [
                {
                    "name": "fake_name",
                    "stream": "fake_stream",
                    "profiles": ["test"],
                }
            ]
        },
        "packages": {},
        "content_sets": {},
    }
    yield UbiConfig.load_from_dict(config_dict, "fake/config.yaml")


def test_ubi_unit():
    """Test proper wrapping *Unit classes of pulplib and access of their attrs"""
    unit = RpmUnit(name="test", version="1.0", release="1", arch="x86_64")

    repo_id = "test_repo_id"
    ubi_unit = UbiUnit(unit, repo_id)

    # we can directly access attrs of RpmUnit
    assert ubi_unit.name == "test"
    assert ubi_unit.version == "1.0"
    assert ubi_unit.release == "1"
    assert ubi_unit.arch == "x86_64"
    assert ubi_unit.associate_source_repo_id == repo_id

    # non-existing attr will raise an error
    with pytest.raises(AttributeError):
        _ = ubi_unit.non_existing_attr


def test_run_raises_exception():
    """Matcher.run() method needs to implemented in subclasses"""
    matcher = Matcher(None, None)
    with pytest.raises(NotImplementedError):
        matcher.run()


def test_search_units(pulp):
    """Test simple search for units"""
    repo = YumRepository(
        id="test_repo",
    )
    repo.__dict__["_client"] = pulp.client

    unit_1 = RpmUnit(name="test", version="1.0", release="1", arch="x86_64")
    unit_2 = RpmUnit(name="test", version="1.0", release="1", arch="i386")
    pulp.insert_repository(repo)
    pulp.insert_units(repo, [unit_1, unit_2])

    matcher = Matcher(None, None)
    criteria = matcher._create_or_criteria(["name", "arch"], [("test", "x86_64")])
    # let Future return result
    search_result = matcher._search_units(repo, criteria, "rpm").result()

    # result should be set
    assert isinstance(search_result, set)
    # with only 1 item
    assert len(search_result) == 1
    unit = search_result.pop()
    # unit should be UbiUnit
    assert isinstance(unit, UbiUnit)
    # internally _unit attr should be RpmUnit
    assert isinstance(unit._unit, RpmUnit)
    # unit has name "test"
    assert unit.name == "test"
    # and proper associate_source_repo_id set
    assert unit.associate_source_repo_id == "test_repo"


def test_create_criteria():
    """Test creation of criteria list"""
    matcher = Matcher(None, None)

    fields = ["color", "size"]
    values = [("blue", "10"), ("white", "15")]

    criteria = matcher._create_or_criteria(fields, values)

    # there should be 2 criteria created
    assert len(criteria) == 2
    # both of instance of Criteria
    for crit in criteria:
        assert isinstance(crit, Criteria)
    # let's not test internal structure of criteria, that's responsibility of pulplib


def test_create_criteria_uneven_args():
    """Test wrong number of values in args"""
    matcher = Matcher(None, None)

    fields = ["color", "size"]
    values = [("blue", "10"), ("white")]
    # call to _create_or_criteria raises ValueError because of uneven number of values of the second tuple
    # in value list
    with pytest.raises(ValueError):
        _ = matcher._create_or_criteria(fields, values)


def test_search_units_per_repos(pulp):
    """Test searching over multiple repositories"""
    repo_1 = YumRepository(
        id="test_repo_1",
    )
    repo_1.__dict__["_client"] = pulp.client

    repo_2 = YumRepository(
        id="test_repo_2",
    )
    repo_2.__dict__["_client"] = pulp.client

    unit_1 = RpmUnit(name="test", version="1.0", release="1", arch="x86_64")
    unit_2 = RpmUnit(name="test", version="1.0", release="1", arch="i386")

    pulp.insert_repository(repo_1)
    pulp.insert_repository(repo_2)
    pulp.insert_units(repo_1, [unit_1])
    pulp.insert_units(repo_2, [unit_2])

    expected_repo_ids = ["test_repo_1", "test_repo_2"]
    matcher = Matcher(None, None)

    criteria = matcher._create_or_criteria(
        ["name", "arch"], [("test", "x86_64"), ("test", "i386")]
    )

    # let Future return result
    search_result = matcher._search_units_per_repos(
        criteria, [repo_1, repo_2], "rpm"
    ).result()
    # result should be set
    assert isinstance(search_result, set)
    # with 2 items
    assert len(search_result) == 2
    # units are from both repos
    actual_repo_ids = []
    for unit in search_result:
        actual_repo_ids.append(unit.associate_source_repo_id)
        assert isinstance(unit, UbiUnit)
    assert sorted(actual_repo_ids) == expected_repo_ids


def test_search_rpms(pulp):
    """Test convenient method for searching rpms"""
    repo = YumRepository(
        id="test_repo_1",
    )
    repo.__dict__["_client"] = pulp.client
    unit_1 = RpmUnit(
        name="test",
        version="1.0",
        release="1",
        arch="x86_64",
        filename="test.x86_64.rpm",
    )
    unit_2 = RpmUnit(
        name="test", version="1.0", release="1", arch="i386", filename="test.i386.rpm"
    )

    pulp.insert_repository(repo)
    pulp.insert_units(repo, [unit_1, unit_2])

    matcher = Matcher(None, None)
    criteria = matcher._create_or_criteria(["filename"], [("test.x86_64.rpm",)])
    # let Future return result
    result = matcher._search_rpms(criteria, [repo]).result()
    # there should be be only one unit in the result set according to criteria
    assert len(result) == 1
    assert result.pop().filename == "test.x86_64.rpm"


def test_search_srpms(pulp):
    """Test convenient method for searching srpms"""
    repo = YumRepository(
        id="test_repo_1",
    )
    repo.__dict__["_client"] = pulp.client
    unit_1 = RpmUnit(
        name="test",
        version="1.0",
        release="1",
        arch="src",
        filename="test.src.rpm",
        content_type_id="srpm",
    )
    unit_2 = RpmUnit(
        name="test-devel",
        version="1.0",
        release="1",
        arch="src",
        filename="test-devel.src.rpm",
        content_type_id="srpm",
    )

    pulp.insert_repository(repo)
    pulp.insert_units(repo, [unit_1, unit_2])

    matcher = Matcher(None, None)
    criteria = matcher._create_or_criteria(["filename"], [("test.src.rpm",)])
    # let Future return result
    result = matcher._search_srpms(criteria, [repo]).result()
    # there should be be only one unit in the result set according to criteria
    assert len(result) == 1
    assert result.pop().filename == "test.src.rpm"


def test_search_moludemds(pulp):
    """Test convenient method for searching modulemds"""
    repo = YumRepository(
        id="test_repo_1",
    )
    repo.__dict__["_client"] = pulp.client
    unit_1 = ModulemdUnit(
        name="test",
        stream="10",
        version=100,
        context="abcdef",
        arch="x86_64",
    )
    unit_2 = ModulemdUnit(
        name="test",
        stream="20",
        version=100,
        context="abcdef",
        arch="x86_64",
    )

    pulp.insert_repository(repo)
    pulp.insert_units(repo, [unit_1, unit_2])

    matcher = Matcher(None, None)
    criteria = matcher._create_or_criteria(["name", "stream"], [("test", "10")])
    # let Future return result
    result = matcher._search_moludemds(criteria, [repo]).result()
    # there should be be only one unit in the result set according to criteria
    assert len(result) == 1
    assert result.pop().nsvca == "test:10:100:abcdef:x86_64"


def test_modular_rpms_filenames(ubi_config):
    """Test getting filename from module artifacts, srpms are skipped."""
    matcher = ModularMatcher(None, ubi_config.modules)
    unit = UbiUnit(
        ModulemdUnit(
            name="test",
            stream="10",
            version=100,
            context="abcd",
            arch="x86_64",
            artifacts=[
                "perl-version-7:0.99.24-441.module+el8.3.0+6718+7f269185.src",
                "perl-version-7:0.99.24-441.module+el8.3.0+6718+7f269185.x86_64",
            ],
        ),
        None,
    )

    modules = f_proxy(f_return(set([unit])))
    filenames = matcher._modular_rpms_filenames(modules)

    # there should be only 1 filename because srpms are skipped
    assert len(filenames) == 1
    assert (
        filenames.pop()
        == "perl-version-0.99.24-441.module+el8.3.0+6718+7f269185.x86_64.rpm"
    )


def test_modular_rpms_filenames_per_profiles(ubi_config):
    """Test getting filename from module artifacts, limited by profiles"""
    matcher = ModularMatcher(None, ubi_config.modules)
    unit = UbiUnit(
        ModulemdUnit(
            name="fake_name",
            stream="fake_stream",
            version=100,
            context="abcd",
            arch="x86_64",
            artifacts=[
                "perl-version-7:0.99.24-441.module+el8.3.0+6718+7f269185.src",
                "perl-7:0.99.24-441.module+el8.3.0+6718+7f269185.x86_64",
                "bash-7:10.5-el6.x86_64",
                "bash-devel-7:0.99.24-441.module+el8.3.0+6718+7f269185.x86_64",
            ],
            profiles={"test": ["perl", "bash"], "another": ["bash"]},
        ),
        None,
    )
    modules = f_proxy(f_return(set([unit])))
    filenames = matcher._modular_rpms_filenames(modules)

    # only pkgs from test profile perl+bash should be in result
    # this result is driven also by ubi_config that force to use only profile called "test"
    assert len(filenames) == 2
    assert filenames == set(
        [
            "bash-10.5-el6.x86_64.rpm",
            "perl-0.99.24-441.module+el8.3.0+6718+7f269185.x86_64.rpm",
        ]
    )


def test_modular_rpms_filenames_per_profiles_missing_profile(ubi_config):
    """Test getting filename from module artifacts, request for non-existing profile in modulemd"""
    matcher = ModularMatcher(None, ubi_config.modules)
    unit = UbiUnit(
        ModulemdUnit(
            name="fake_name",
            stream="fake_stream",
            version=100,
            context="abcd",
            arch="x86_64",
            artifacts=[
                "perl-version-7:0.99.24-441.module+el8.3.0+6718+7f269185.src",
                "perl-7:0.99.24-441.module+el8.3.0+6718+7f269185.x86_64",
                "bash-7:10.5-el6.x86_64",
                "bash-devel-7:0.99.24-441.module+el8.3.0+6718+7f269185.x86_64",
            ],
            profiles={"another": ["bash"]},
        ),
        None,
    )
    modules = f_proxy(f_return(set([unit])))
    filenames = matcher._modular_rpms_filenames(modules)

    # all non-src pkgs are in result
    # this result is driven by ubi_config that force to use only profile called "test"
    # but we don't have this profile in the testing modulemd, so we take all non-src artifacts
    assert len(filenames) == 3
    assert filenames == set(
        [
            "bash-10.5-el6.x86_64.rpm",
            "bash-devel-0.99.24-441.module+el8.3.0+6718+7f269185.x86_64.rpm",
            "perl-0.99.24-441.module+el8.3.0+6718+7f269185.x86_64.rpm",
        ]
    )


def test_keep_n_latest_modules():
    """Test keeping only the latest version of modulemd"""
    unit_1 = UbiUnit(
        ModulemdUnit(
            name="test", stream="10", version=100, context="abcd", arch="x86_64"
        ),
        None,
    )

    unit_2 = UbiUnit(
        ModulemdUnit(
            name="test", stream="10", version=101, context="abcd", arch="x86_64"
        ),
        None,
    )

    matcher = ModularMatcher(None, None)
    modules = [unit_1, unit_2]
    matcher._keep_n_latest_modules(modules)

    # there should only one modulemd
    assert len(modules) == 1
    # with the highest number of version
    assert modules.pop().version == 101


def test_keep_n_latest_modules_different_context():
    """Test keeping only the latest version of modulemds with the different context"""
    unit_1 = UbiUnit(
        ModulemdUnit(
            name="test", stream="10", version=100, context="abcd", arch="x86_64"
        ),
        None,
    )

    unit_2 = UbiUnit(
        ModulemdUnit(
            name="test", stream="10", version=100, context="xyz", arch="x86_64"
        ),
        None,
    )
    unit_3 = UbiUnit(
        ModulemdUnit(
            name="test", stream="10", version=99, context="xyz", arch="x86_64"
        ),
        None,
    )

    matcher = ModularMatcher(None, None)  ## TODO do fixtures
    modules = [unit_1, unit_2, unit_3]
    matcher._keep_n_latest_modules(modules)
    expected_contexts = ["abcd", "xyz"]

    # both of modulemd should be in result
    assert len(modules) == 2
    actual_contexts = []
    versions = set()
    for module in modules:
        actual_contexts.append(module.context)
        versions.add(module.version)
    # the should have different contexts
    assert sorted(actual_contexts) == expected_contexts
    # but only modules with the highest version are kept
    assert len(versions) == 1
    assert versions.pop() == 100


def test_get_modulemd_output_set():
    """Test creation of modulemd output set for ubipop"""
    unit_1 = UbiUnit(
        ModulemdUnit(
            name="test", stream="10", version=100, context="abcd", arch="x86_64"
        ),
        None,
    )

    unit_2 = UbiUnit(
        ModulemdUnit(
            name="test", stream="10", version=101, context="xyz", arch="x86_64"
        ),
        None,
    )

    unit_3 = UbiUnit(
        ModulemdUnit(
            name="test", stream="20", version=100, context="xyz", arch="x86_64"
        ),
        None,
    )

    matcher = ModularMatcher(None, None)
    output_set = matcher._get_modulemd_output_set([unit_1, unit_2, unit_3])

    assert isinstance(output_set, list)
    # In output_set, we should have only the latest version of modulemds
    # of the same name and stream
    assert sorted(output_set, key=attrgetter("_unit")) == [unit_2, unit_3]


def test_get_modulemds_criteria(ubi_config):
    """Test proper creation of criteria for modulemds query"""
    matcher = ModularMatcher(None, ubi_config.modules)
    criteria = matcher._get_modulemds_criteria()
    # there should be 1 criterium created based on ubi config
    assert len(criteria) == 1
    # it should be instance of Criteria
    for crit in criteria:
        assert isinstance(crit, Criteria)
    # let's not test internal structure of criteria, that's responsibility of pulplib


def test_get_modular_srpms_criteria(ubi_config):
    """Testing creation of criteria for srpms query"""
    matcher = ModularMatcher(None, ubi_config.modules)
    unit_1 = UbiUnit(
        RpmUnit(
            name="test",
            version="1.0",
            release="1",
            arch="x86_64",
            sourcerpm="test.x86_64.src.rpm",
        ),
        None,
    )
    unit_2 = UbiUnit(
        RpmUnit(
            name="test-debug",
            version="1.0",
            release="1",
            arch="i386",
            sourcerpm="test-debug.i386.src.rpm",
        ),
        None,
    )

    # we need to set up binary and debug rpms
    # the criteria are based on sourcerpm attr of those units
    matcher.binary_rpms = f_proxy(f_return(set([unit_1])))
    matcher.debug_rpms = f_proxy(f_return(set([unit_2])))

    criteria = matcher._get_modular_srpms_criteria()
    # there should be 1 criteria created
    assert len(criteria) == 2
    # it should be instance of Criteria
    for crit in criteria:
        assert isinstance(crit, Criteria)
    # let's not test internal structure of criteria, that's responsibility of pulplib


def test_get_modular_rpms_criteria(ubi_config):
    """Test creation of criteria for rpms query"""
    matcher = ModularMatcher(None, ubi_config.modules)
    unit = UbiUnit(
        ModulemdUnit(
            name="test",
            stream="10",
            version=100,
            context="abcd",
            arch="x86_64",
            artifacts=[
                "perl-version-7:0.99.24-441.module+el8.3.0+6718+7f269185.src",
                "perl-version-7:0.99.24-441.module+el8.3.0+6718+7f269185.x86_64",
            ],
        ),
        None,
    )
    matcher.modules = f_proxy(f_return(set([unit])))
    criteria = matcher._get_modular_rpms_criteria()

    # there should be 1 criterium created - srpm is skipped
    assert len(criteria) == 1
    # it should be instance of Criteria
    for crit in criteria:
        assert isinstance(crit, Criteria)
    # let's not test internal structure of criteria, that's responsibility of pulplib


def test_modular_matcher_run(pulp, ubi_config):
    """Test run() method which asynchronously creates criteria for queries to pulp
    and exectues those query. Finally it sets up public attrs of the ModularMatcher
    object that can be used in ubipop"""

    repo_1 = YumRepository(
        id="binary_repo",
    )
    repo_1.__dict__["_client"] = pulp.client

    repo_2 = YumRepository(
        id="debug_repo",
    )
    repo_2.__dict__["_client"] = pulp.client
    repo_3 = YumRepository(
        id="source_repo",
    )
    repo_3.__dict__["_client"] = pulp.client

    # binary
    unit_1 = RpmUnit(
        name="test",
        version="1.0",
        release="1",
        arch="x86_64",
        filename="test-1.0-1.x86_64.x86_64.rpm",
        sourcerpm="test-1.0-1.x86_64.src.rpm",
    )
    # debug
    unit_2 = RpmUnit(
        name="test-debug",
        version="1.0",
        release="1",
        arch="x86_64",
        filename="test-debug-1.0-1.x86_64.rpm",
    )
    # source
    unit_3 = RpmUnit(
        name="test-src",
        version="1.0",
        release="1",
        arch="src",
        filename="test-1.0-1.x86_64.src.rpm",
        content_type_id="srpm",
    )

    modulemd = ModulemdUnit(
        name="fake_name",
        stream="fake_stream",
        version=100,
        context="abcd",
        arch="x86_64",
        artifacts=[
            "test-7:1.0-1.x86_64.x86_64",
            "test-debug-7:1.0-1.x86_64",
            "test-7:1.0-1.x86_64.src",
        ],
    )
    pulp.insert_repository(repo_1)
    pulp.insert_repository(repo_2)
    pulp.insert_repository(repo_3)
    pulp.insert_units(repo_1, [unit_1, modulemd])
    pulp.insert_units(repo_2, [unit_2])
    pulp.insert_units(repo_3, [unit_3])

    repos_set = RepoSet(rpm=[repo_1], debug=[repo_2], source=[repo_3])
    matcher = ModularMatcher(repos_set, ubi_config.modules)
    matcher.run()

    # each public attribute is properly set with one unit
    assert len(matcher.modules) == 1
    assert len(matcher.binary_rpms) == 1
    assert len(matcher.debug_rpms) == 1
    assert len(matcher.source_rpms) == 1

    # each unit is properly queried
    output_module = matcher.modules.pop()
    assert output_module.nsvca == "fake_name:fake_stream:100:abcd:x86_64"
    assert output_module.associate_source_repo_id == "binary_repo"

    rpm = matcher.binary_rpms.pop()
    assert rpm.filename == "test-1.0-1.x86_64.x86_64.rpm"
    assert rpm.associate_source_repo_id == "binary_repo"

    rpm = matcher.debug_rpms.pop()
    assert rpm.filename == "test-debug-1.0-1.x86_64.rpm"
    assert rpm.associate_source_repo_id == "debug_repo"

    rpm = matcher.source_rpms.pop()
    assert rpm.filename == "test-1.0-1.x86_64.src.rpm"
    assert rpm.associate_source_repo_id == "source_repo"


def test_flatten_list_of_sets():
    """Test helper function that flattens list of sets into one set"""
    set_1 = set([1, 2, 3])
    set_2 = set([2, 3, 4])
    expected_set = set([1, 2, 3, 4])

    new_set = flatten_list_of_sets([set_1, set_2]).result()
    assert new_set == expected_set