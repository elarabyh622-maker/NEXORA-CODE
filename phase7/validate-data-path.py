"""Check the Data Analysis release and run its repository-authored Python cases locally."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


PHASE = Path(__file__).resolve().parent
BASE = PHASE.parent / "phase4/dist/curriculum.json"
BASE_SHA256 = "378ddc4d0405fd978efd6c2a56c8a419da73cecd553d1fef5f011e3b3d397743"
MODULES = ("data-foundations", "data-project")
DATA_LESSONS = [f"data-{index:02}" for index in range(1, 9)]
DATA_GOAL = "data-analysis"
RELEASE = "phase7-ar-v1"
MAX_OUTPUT_BYTES = 16 * 1024
TIMEOUT_SECONDS = 4


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ids(rows):
    return [row["id"] for row in rows]


def combined(modules, key):
    return [row for module in modules for row in module[key]]


def private_material_is_present(value, solutions):
    if isinstance(value, dict):
        return any(key.lower() in {"solution", "examplechecks"} or private_material_is_present(item, solutions)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(private_material_is_present(item, solutions) for item in value)
    return isinstance(value, str) and any(solution in value.replace("\r\n", "\n") for solution in solutions)


def check_release(base, release, modules):
    sample, graph = release["sample"], release["graph"]
    require(sample["releaseId"] == graph["releaseId"] == RELEASE,
            "sample and graph must share the new release identifier")
    lessons = combined(modules, "lessons")
    graph_lessons = combined(modules, "graphLessons")
    skills = combined(modules, "skills")
    labs = combined(modules, "labs")
    require(ids(lessons) == ids(graph_lessons) == DATA_LESSONS,
            "lesson and graph sources must contain data-01 through data-08 in order")
    require(len(skills) == len(lessons) and all(skill["id"].startswith("data.") for skill in skills),
            "every new lesson must introduce a Data Analysis skill")
    require([skill for lesson in graph_lessons for skill in lesson["skillIds"]] == ids(skills),
            "the new graph lessons must teach the Data Analysis skills in order")
    require([lesson["skillIds"] for lesson in lessons] == [lesson["skillIds"] for lesson in graph_lessons],
            "lesson and graph skills must agree")
    require(skills[0]["required"] == {"skill": "py.automation"},
            "the new path must start after Python automation")
    require(all(current["required"] == {"skill": previous["id"]} for previous, current in zip(skills, skills[1:])),
            "the Data Analysis skills must form a sequential prerequisite chain")
    require(all(len(lesson["exercises"]) >= 2 for lesson in lessons),
            "every new lesson must have at least two graded exercises")
    require(len(labs) >= 4, "the Data Analysis track must have at least four labs")

    import_labs = [{key: value for key, value in lab.items() if key != "solution"} for lab in labs]
    expected = ((sample["lessons"], base["sample"]["lessons"] + lessons, "sample lessons"),
                (graph["lessons"], base["graph"]["lessons"] + graph_lessons, "graph lessons"),
                (graph["skills"], base["graph"]["skills"] + skills, "skills"),
                (release["codeLab"], base["codeLab"] + import_labs, "lab definitions"))
    for actual, expected_rows, label in expected:
        require(actual == expected_rows, f"{label} differ from Phase 4 plus the reviewed new rows")

    for key, current, prior in (("tracks", sample, base["sample"]), ("goals", graph, base["graph"])):
        old_rows = prior[key]
        require(current[key][:-1] == old_rows and ids(current[key][-1:]) == [DATA_GOAL],
                f"{key} must preserve Phase 4 and add one Data Analysis entry")
    require(sample["tracks"][-1]["lessonIds"] == DATA_LESSONS and graph["goals"][-1]["skillIds"] == ids(skills),
            "the new track and goal must point to the Data Analysis lessons and skills")
    project = modules[1]["project"]
    require(project["lessonId"] == DATA_LESSONS[-1] and sample["projects"] == base["sample"]["projects"] + [project],
            "projects must preserve Phase 4 and add one Data Analysis capstone")
    glossary = {}
    for entry in base["sample"]["glossary"] + combined(modules, "glossary"):
        glossary.setdefault(entry["term"], entry)
    require(sample["glossary"] == list(glossary.values()),
            "the release must preserve the Phase 4 glossary and add each new term exactly once")

    exercises = [exercise for lesson in sample["lessons"] for exercise in lesson["exercises"]]
    for rows, label in ((sample["lessons"], "lesson"), (exercises, "exercise"), (graph["skills"], "skill"),
                        (release["codeLab"], "lab"), (sample["projects"], "project")):
        require(len(rows) == len(set(ids(rows))), f"duplicate {label} identifier")
    solutions = [lab["solution"].replace("\r\n", "\n").strip() for lab in labs]
    require(all(solutions), "the new labs must have private reference solutions")
    require(not private_material_is_present(release, solutions),
            "a private lab solution or case manifest is in the release")
    return lessons, labs


def normalize_output(output):
    return output.replace("\r\n", "\n").removesuffix("\n")


def run_python(code, data):
    # Fixed, repository-authored source only. Python's isolated mode is not a sandbox.
    env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR") if name in os.environ}
    result = subprocess.run([sys.executable, "-I", "-X", "utf8", "-B", "-c", code],
                            input=data.encode("utf-8"), capture_output=True, cwd=PHASE,
                            env=env, timeout=TIMEOUT_SECONDS, check=False)
    require(len(result.stdout) + len(result.stderr) <= MAX_OUTPUT_BYTES, "output exceeded the runner limit")
    require(result.returncode == 0, f"Python exited with status {result.returncode}")
    require(not result.stderr, "Python wrote to stderr")
    return normalize_output(result.stdout.decode("utf-8"))


def verify_case(label, code, data, expected):
    try:
        actual = run_python(code, data)
        require(actual == normalize_output(expected), "stdout differed from the expected output")
    except subprocess.TimeoutExpired:
        raise ValueError(f"{label}: Python exceeded {TIMEOUT_SECONDS} seconds") from None
    except ValueError as error:
        raise ValueError(f"{label}: {error}") from None


def check_examples(lessons, modules):
    examples = {}
    for lesson in lessons:
        for index, example in enumerate(lesson["examples"]):
            require(example["language"] == "python", f"{lesson['id']} has a non-Python example")
            examples[lesson["id"], index] = example
    cases = combined(modules, "exampleChecks")
    keys = [(case["lessonId"], case["index"]) for case in cases]
    require(len(keys) == len(set(keys)) and set(keys) == examples.keys(),
            "every Python example must have exactly one execution case")
    require({lesson_id for lesson_id, _ in keys} == set(DATA_LESSONS),
            "every new lesson must have a runnable example")
    for key, case in zip(keys, cases):
        lesson_id, index = key
        verify_case(f"{lesson_id} example {index + 1}", examples[key]["code"], case["input"], case["output"])
    print(f"PASSED: {len(cases)} Python console examples")


def check_labs(lessons, labs):
    lesson_skills = {lesson["id"]: lesson["skillIds"] for lesson in lessons}
    case_count = 0
    for lab in labs:
        lab_id = lab["id"]
        require(lab["language"] == "python" and lab["skillId"] in lesson_skills.get(lab["lessonId"], []),
                f"{lab_id} must be a Python lab attached to a matching lesson and skill")
        hidden = lab["hiddenTests"]
        require(1 <= len(hidden) <= 3, f"{lab_id} must have one to three hidden cases")
        cases = [{"input": lab["sampleInput"], "expectedOutput": lab["sampleOutput"]}, *hidden]
        require(len({case["input"] for case in cases}) == len(cases), f"{lab_id} repeats an input")
        require(any(normalize_output(case["expectedOutput"]) != normalize_output(lab["sampleOutput"])
                    for case in hidden), f"{lab_id} hidden cases would accept the printed sample output")
        for index, case in enumerate(cases, 1):
            verify_case(f"{lab_id} case {index}", lab["solution"], case["input"], case["expectedOutput"])
        case_count += len(cases)
    print(f"PASSED: {case_count} reference cases across {len(labs)} labs, including hidden cases")


def check_capstone(labs):
    capstone = next((lab for lab in labs if lab["lessonId"] == DATA_LESSONS[-1]), None)
    require(capstone is not None, "the capstone must have a Python lab")
    verify_case(
        "capstone quoted Arabic activity and extra fields",
        capstone["solution"],
        'activity,attended,offered,notes\n" قراءة, جماعية ",2,5,ignored\nRead,3,4,more\nread,0,3\n',
        "valid=3\ninvalid=0\nactivity:Read attended=3 offered=4 rate=75.0%\n"
        "activity:read attended=0 offered=3 rate=0.0%\nactivity:قراءة, جماعية attended=2 offered=5 rate=40.0%\n"
        "total:attended=5 offered=12 rate=41.7%\ntop=Read\nscope=valid fictional rows only\n",
    )
    verify_case(
        "capstone all rows invalid",
        capstone["solution"],
        "activity,attended,offered\nA,1,0\nB,0,-1\nC,1\n ,0,0\n",
        "valid=0\ninvalid=4\ntotal:attended=0 offered=0 rate=NA\ntop=none\nscope=valid fictional rows only\n",
    )
    print("PASSED: two additional capstone edge cases")


def main():
    try:
        require(hashlib.sha256(BASE.read_bytes()).hexdigest() == BASE_SHA256,
                "the Phase 4 curriculum file changed")
        base = load_json(BASE)
        release = load_json(PHASE / "dist/curriculum.json")
        modules = [load_json(PHASE / f"content/{module}.json") for module in MODULES]
        lessons, labs = check_release(base, release, modules)
        print("PASSED: Phase 4 preserved, eight Data Analysis lessons added, and private reference code excluded")
        check_examples(lessons, modules)
        check_labs(lessons, labs)
        check_capstone(labs)
    except (KeyError, OSError, ValueError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
