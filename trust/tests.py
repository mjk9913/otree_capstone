import time
from contextlib import contextmanager

from otree.api import *
from otree import settings

from ..real_effort import Group, Puzzle, Game


class PlayerBot(Bot):
    cases = [
        "normal",  # solving 2 puzzles in normal sequence
        "replying_correct",  # giving a correct answer
        "replying_incorrect",  # giving an incorrect answer
        "messaging_bogus",  # sending bogus message
        "replying_null",  # giving null as an answer
        "replying_empty",  # giving empty string as an answer
        "replying_premature",  # giving reply without current puzzle
        "forward_nodelay",  # advancing to a next puzzle w/out delay
        "reloading_start",  # page reload at the start of a round
        "reloading_midgame",  # page reload in the middle of a round
        "skipping_unanswered",  # advancing to a next puzzle w/out replying
        "skipping_incorrect",  # advancing to a next puzzle after incorrect answer
        "retrying_correct",  # answering to the same puzzle correctly after incorrect answer
        "retrying_incorrect",  # answering the same puzzle incorrectly after correct answer, for no reason
        "retrying_nodelay",  # retrying w/out delay
        "retrying_many",  # retrying many times
        "retrying_limit",  # retrying too many times
        "iter_limit",  # exchausting number of iterations
        "cheat_debug",
        "cheat_nodebug",
    ]

    def play_round(self):
        if self.case == 'iter_limit' and not self.session.params['max_iterations']:
            print(f"Skipping case {self.case} under no max_iterations")
            return

        make_timeout = self.case != 'iter_limit'
        yield Submission(Game, check_html=False, timeout_happened=make_timeout)

        group = self.group
        num_correct = len(Puzzle.filter(group=group, is_correct=True))
        num_incorrect = len(Puzzle.filter(group=group, is_correct=False))

        expect(group.num_correct, num_correct)
        expect(group.num_failed, num_incorrect)
        expect(group.num_trials, num_correct + num_incorrect)


def get_last_puzzle(group: Group) -> Puzzle:
    puzzles = Puzzle.filter(group=group, iteration=group.iteration)
    puzzle = puzzles[-1] if len(puzzles) else None
    return puzzle


# utils
# `m` stands for method, `p` for player


@contextmanager
def expect_failure(*exceptions):
    try:
        yield
    except exceptions:
        return
    except Exception as e:
        raise AssertionError(
            f"A piece of code was expected to fail with {exceptions} but it failed with {e.__class__}"
        )
    raise AssertionError(
        f"A piece of code was expected to fail with {exceptions} but it didn't"
    )


def get_last_puzzle_clone(p):
    # makes a clone to check changes of the same instance
    data = Puzzle.values_dicts(group=p)  # noqa
    if len(data) == 0:
        return None
    datum = data[-1]
    return Puzzle(**datum)  # noqa


def get_progress(p):
    return {
        "total": len(Puzzle.filter(group=p)),
        "correct": len(Puzzle.filter(group=p, is_correct=True)),
        "incorrect": len(Puzzle.filter(group=p, is_correct=False)),
    }


def reload(m, p):
    return m(p.id_in_group, dict(type='load'))[p.id_in_group]


def move_forward(m, p):
    return m(p.id_in_group, dict(type='next'))[p.id_in_group]


def expect_forwarded(p, _last):
    _puzzle = get_last_puzzle(p)
    expect(_puzzle.id, "!=", _last.id)
    expect(_puzzle.timestamp, ">", _last.timestamp)
    expect(_puzzle.iteration, ">", _last.iteration)


def expect_not_forwarded(p, _last):
    _puzzle = get_last_puzzle(p)
    expect(_puzzle.id, "==", _last.id)
    expect(_puzzle.timestamp, "==", _last.timestamp)
    expect(_puzzle.iteration, "==", _last.iteration)


def solution(p):
    _puzzle = get_last_puzzle(p)
    return _puzzle.solution


def give_answer(m, p, ans):
    _response = m(p.id_in_group, dict(type="answer", answer=ans))[p.id_in_group]
    return _response


def expect_progress(p, **values):
    progress = get_progress(p)
    expect(progress, values)


def expect_answered(p, ans, correct=None):
    _puzzle = get_last_puzzle(p)

    # make it work for both strings and numbers
    expect(str(_puzzle.response), str(ans))

    expect(_puzzle.response_timestamp, ">", _puzzle.timestamp)
    if correct is not None:
        expect(_puzzle.is_correct, correct)


def expect_answered_correctly(p, ans):
    expect_answered(p, ans, True)


def expect_answered_incorrectly(p, ans):
    expect_answered(p, ans, False)


def expect_reanswered(p, lst):
    # NB: `last` should be a clone of Puzzle
    _puzzle = get_last_puzzle(p)
    expect(_puzzle.response_timestamp, ">", lst.response_timestamp)
    expect(_puzzle.attempts, ">", lst.attempts)


def expect_not_reanswered(p, lst):
    # NB: `last` should be a clone of Puzzle
    _puzzle = get_last_puzzle(p)
    expect(_puzzle.response_timestamp, "==", lst.response_timestamp)
    expect(_puzzle.attempts, "==", lst.attempts)


def expect_not_answered(p):
    _puzzle = get_last_puzzle(p)
    expect(_puzzle.response, None)
    expect(_puzzle.is_correct, None)


def expect_response_status(response):
    expect(response['type'], 'status')
    expect("progress", "in", response)


def expect_response_puzzle(response):
    expect(response['type'], 'puzzle')
    expect("puzzle", "in", response)
    expect("image", "in", response["puzzle"])
    expect(response["puzzle"]["image"].startswith("data:text/plain;base64"), True)


def expect_response_progress(response, **values):
    expect("progress", "in", response)
    expect(response["progress"], values)


def expect_response_correct(response):
    expect(response['type'], 'feedback')
    expect("is_correct", "in", response)
    expect(response["is_correct"], True)


def expect_response_incorrect(response):
    expect(response['type'], 'feedback')
    expect("is_correct", "in", response)
    expect(response["is_correct"], False)


# test case dispatching


def call_live_method(method, group, case, **kwargs):  # noqa
    print(f"Testing case '{case}'")

    try:
        test = globals()[f"live_test_{case}"]
    except KeyError:
        raise NotImplementedError("Test case not implemented", case)

    test(method, group.get_players()[0], group.session.params)


# test cases


def live_test_normal(method, group, conf):
    puzzle_delay = conf['puzzle_delay']

    # part of normal flow, checking everything
    resp = reload(method, group)
    expect_response_status(resp)
    expect_progress(group, total=0, correct=0, incorrect=0)
    expect_response_progress(
        resp, iteration=0, num_trials=0, num_correct=0, num_incorrect=0
    )

    # 1st puzzle
    resp = move_forward(method, group)
    expect_progress(group, total=1, correct=0, incorrect=0)
    expect_response_puzzle(resp)
    expect_response_progress(
        resp, iteration=1, num_trials=0, num_correct=0, num_incorrect=0
    )

    last = get_last_puzzle(group)

    answer = solution(group)
    resp = give_answer(method, group, answer)
    expect_answered_correctly(group, answer)
    expect_progress(group, total=1, correct=1, incorrect=0)
    expect_not_forwarded(group, last)
    expect_response_correct(resp)
    expect_response_progress(
        resp, iteration=1, num_trials=1, num_correct=1, num_incorrect=0
    )

    time.sleep(puzzle_delay)

    # 2nd puzzle
    resp = move_forward(method, pgroup)
    expect_progress(group, total=2, correct=1, incorrect=0)
    expect_response_puzzle(resp)
    expect_response_progress(
        resp, iteration=2, num_trials=1, num_correct=1, num_incorrect=0
    )

    last = get_last_puzzle(group)

    answer = solution(group)
    resp = give_answer(method, group, answer)
    expect_answered_correctly(group, answer)
    expect_progress(group, total=2, correct=2, incorrect=0)
    expect_not_forwarded(group, last)
    expect_response_correct(resp)
    expect_response_progress(
        resp, iteration=2, num_trials=2, num_correct=2, num_incorrect=0
    )


def live_test_replying_correct(method, group, conf):
    resp = move_forward(method, group)
    expect_progress(group, total=1, correct=0, incorrect=0)
    expect_response_puzzle(resp)
    expect_response_progress(
        resp, iteration=1, num_trials=0, num_correct=0, num_incorrect=0
    )

    answer = solution(group)
    resp = give_answer(method, group, answer)
    expect_answered_correctly(group, answer)
    expect_progress(group, total=1, correct=1, incorrect=0)
    expect_response_correct(resp)
    expect_response_progress(
        resp, iteration=1, num_trials=1, num_correct=1, num_incorrect=0
    )


def live_test_replying_incorrect(method, group, conf):
    resp = move_forward(method, group)
    expect_progress(group, total=1, correct=0, incorrect=0)
    expect_response_puzzle(resp)
    expect_response_progress(
        resp, iteration=1, num_trials=0, num_correct=0, num_incorrect=0
    )

    answer = "0"  # should work as invalid both for string and numeric
    resp = give_answer(method, group, answer)
    expect_answered_incorrectly(group, answer)
    expect_progress(group, total=1, correct=0, incorrect=1)
    expect_response_incorrect(resp)
    expect_response_progress(
        resp, iteration=1, num_trials=1, num_correct=0, num_incorrect=1
    )


def live_test_messaging_bogus(method, group, conf):
    with expect_failure(TypeError):
        method(group.id_in_group, "BOGUS")


def live_test_reloading_start(method, group, conf):
    # initial load
    resp = reload(method, group)
    expect_progress(group, total=0, correct=0, incorrect=0)
    expect_response_status(resp)
    expect_response_progress(
        resp, iteration=0, num_trials=0, num_correct=0, num_incorrect=0
    )
    expect(get_last_puzzle(group), None)


def live_test_reloading_midgame(method, group, conf):
    resp = reload(method,group)
    expect_progress(group, total=0, correct=0, incorrect=0)
    expect_response_status(resp)

    # first trial
    move_forward(method, group)
    expect_progress(group, total=1, correct=0, incorrect=0)
    last = get_last_puzzle(group)

    # midgame reload
    resp = reload(method, group)
    expect_progress(group, total=1, correct=0, incorrect=0)
    expect(get_last_puzzle(group), last)
    expect_response_status(resp)
    expect_response_progress(
        resp, iteration=1, num_trials=0, num_correct=0, num_incorrect=0
    )


def live_test_replying_empty(method, group, conf):
    move_forward(method, group)
    with expect_failure(ValueError):
        give_answer(method, group, "")
    expect_not_answered(group)


def live_test_replying_null(method, group, conf):
    move_forward(method, group)
    with expect_failure(ValueError):
        give_answer(method, group, None)
    expect_not_answered(group)


def live_test_replying_premature(method, group, conf):
    last = get_last_puzzle(group)
    expect(last, None)
    answer = "123"
    with expect_failure(RuntimeError):
        give_answer(method, group, answer)


def live_test_retrying_correct(method, group, conf):
    retry_delay = conf['retry_delay']
    retry_limit = conf['attempts_per_puzzle']
    allow_retry = retry_limit > 1

    move_forward(method, group)

    # 1st incorrect answer
    answer1 = "0"
    give_answer(method, group, answer1)
    expect_answered_incorrectly(group, answer1)
    expect_progress(group, total=1, correct=0, incorrect=1)

    last = get_last_puzzle_clone(group)

    time.sleep(retry_delay)

    # 2nd correct answer
    answer2 = solution(group)

    if allow_retry:
        give_answer(method, group, answer2)
        get_last_puzzle(group)
        expect_reanswered(group, last)
        expect_answered_correctly(group, answer2)
        expect_progress(group, total=1, correct=1, incorrect=0)
    else:
        with expect_failure(RuntimeError):
            give_answer(method, group, answer2)
        expect_not_reanswered(group, last)
        # state not changed
        expect_answered_incorrectly(pgroup, answer1)
        expect_progress(group, total=1, correct=0, incorrect=1)


def live_test_retrying_incorrect(method, group, conf):
    retry_delay = conf['retry_delay']
    retry_limit = conf['attempts_per_puzzle']
    allow_retry = retry_limit > 1

    move_forward(method, group)

    # 1st correct answer
    answer1 = solution(group)
    give_answer(method, group, answer1)
    expect_answered_correctly(group, answer1)
    expect_progress(group, total=1, correct=1, incorrect=0)

    last = get_last_puzzle_clone(group)

    time.sleep(retry_delay)

    # 2nd incorrect answer
    answer2 = "0"

    if allow_retry:
        give_answer(method, group, answer2)
        expect_reanswered(group, last)
        expect_answered_incorrectly(group, answer2)
        expect_progress(group, total=1, correct=0, incorrect=1)
    else:
        with expect_failure(RuntimeError):
            give_answer(method, group, answer2)
        expect_not_reanswered(group, last)
        # state not changed
        expect_answered_correctly(group, answer1)
        expect_progress(group, total=1, correct=1, incorrect=0)


def live_test_retrying_nodelay(method, group, conf):
    move_forward(method, group)

    # 1st incorrect answer
    answer1 = "0"
    give_answer(method, groupr, answer1)
    expect_answered_incorrectly(group, answer1)
    expect_progress(group, total=1, correct=0, incorrect=1)

    last = get_last_puzzle_clone(group)

    # 2nd correct answer
    answer2 = solution(group)

    # no matter if retry is allowed or not
    with expect_failure(RuntimeError):
        give_answer(method, group, answer2)
    expect_not_reanswered(group, last)
    # state not changed
    expect_answered_incorrectly(group, answer1)
    expect_progress(group, total=1, correct=0, incorrect=1)


def live_test_retrying_many(method, group, conf):
    retry_delay = conf['retry_delay']
    retry_limit = conf['attempts_per_puzzle']

    if retry_limit == 1:
        return

    move_forward(method, group)
    expect_progress(group, total=1, correct=0, incorrect=0)

    answer1 = "0"
    for _ in range(retry_limit - 1):
        give_answer(method, group, answer1)
        expect_answered_incorrectly(group, answer1)
        expect_progress(group, total=1, correct=0, incorrect=1)
        time.sleep(retry_delay)

    last = get_last_puzzle_clone(group)

    answer2 = solution(group)
    give_answer(method, group, answer2)
    expect_reanswered(group, last)
    expect_answered_correctly(group, answer2)
    expect_progress(group, total=1, correct=1, incorrect=0)


def live_test_retrying_limit(method, group, conf):
    retry_delay = conf['retry_delay']
    retry_limit = conf['attempts_per_puzzle']
    if retry_limit == 1:
        return

    move_forward(method, group)
    expect_progress(group, total=1, correct=0, incorrect=0)

    answer1 = "0"
    for _ in range(retry_limit):
        give_answer(method, group, answer1)
        expect_answered_incorrectly(group, answer1)
        expect_progress(group, total=1, correct=0, incorrect=1)
        time.sleep(retry_delay)

    last = get_last_puzzle_clone(group)

    answer2 = solution(group)
    with expect_failure(RuntimeError):
        give_answer(method, group, answer2)
    expect_not_reanswered(group, last)
    expect_answered_incorrectly(group, answer1)
    expect_progress(group, total=1, correct=0, incorrect=1)


def live_test_forward_nodelay(method, group, conf):
    move_forward(method, group)
    last = get_last_puzzle(group)

    answer = solution(group)
    give_answer(method, group, answer)

    with expect_failure(RuntimeError):
        move_forward(method, group)
    expect_not_forwarded(group, last)


def live_test_skipping_unanswered(method, group, conf):
    puzzle_delay = conf['puzzle_delay']

    move_forward(method, group)
    expect_progress(group, total=1, correct=0, incorrect=0)
    last = get_last_puzzle(group)

    time.sleep(puzzle_delay)

    with expect_failure(RuntimeError):
        move_forward(method, group)
    expect_not_forwarded(group, last)
    expect_progress(group, total=1, correct=0, incorrect=0)


def live_test_skipping_incorrect(method, group, conf):
    puzzle_delay = conf['puzzle_delay']
    force_solve = False

    move_forward(method, group)
    expect_progress(group, total=1, correct=0, incorrect=0)
    last = get_last_puzzle(group)

    answer = "0"  # should work as invalid both for string and numeric
    give_answer(method, group, answer)
    expect_answered_incorrectly(groupr, answer)
    expect_progress(group, total=1, correct=0, incorrect=1)

    time.sleep(puzzle_delay)

    if force_solve:
        with expect_failure(RuntimeError):
            move_forward(method, group)
        expect_not_forwarded(group, last)
        expect_progress(group, total=1, correct=0, incorrect=1)
    else:  # just a part of normal flow
        move_forward(method, group)
        expect_forwarded(group, last)
        expect_progress(group, total=2, correct=0, incorrect=1)


def live_test_iter_limit(method, group, conf):
    puzzle_delay = conf['puzzle_delay']
    max_iter = conf['max_iterations']

    # exhaust all iterations

    for _ in range(max_iter):
        move_forward(method, group)
        answer = solution(group)
        give_answer(method, group, answer)
        time.sleep(puzzle_delay)

    expect_progress(group, total=max_iter, correct=max_iter, incorrect=0)
    last = get_last_puzzle_clone(group)

    resp = move_forward(method, group)
    expect_not_forwarded(group, last)
    expect_response_status(resp)
    expect(resp['iterations_left'], 0)


def live_test_cheat_debug(method, group, conf):
    settings.DEBUG = True
    move_forward(method, group)

    resp = method(group.id_in_group, dict(type='cheat'))[group.id_in_group]
    expect("solution", "in", resp)

    answer = resp["solution"]
    resp = give_answer(method, group, answer)
    expect_answered_correctly(group, answer)
    expect_response_correct(resp)


def live_test_cheat_nodebug(method, group, conf):
    settings.DEBUG = False
    move_forward(method, group)
    with expect_failure(RuntimeError):
        method(group.id_in_group, dict(type='cheat'))


def live_test_fake_submit(method, group, conf):
    pass
