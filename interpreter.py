from dataclasses import dataclass
from enum import Enum, auto


GRID_SIZE = 9
START_X = 4
START_Y = 4
START_DIRECTION = 0

_DIRECTION_X = (1, 0, -1, 0)
_DIRECTION_Y = (0, 1, 0, -1)
_WHITESPACE = " \t\r"
_DIACRITICS = str.maketrans({"ľ": "l", "ž": "z"})


@dataclass(frozen=True, slots=True)
class SceneState:
    """Final brick grid and robot pose.

    ``grid`` is indexed as ``grid[y][x]``. Directions match the browser
    interpreter: 0 is +x, 1 is +y, 2 is -x, and 3 is -y.
    """

    grid: tuple[tuple[int, ...], ...]
    robot_x: int
    robot_y: int
    robot_direction: int


class InterpreterError(Exception):
    """Base class for errors produced by a robot program."""


class ParseError(InterpreterError):
    def __init__(self, message: str, line: int):
        self.message = message
        self.line = line
        super().__init__(f"line {line}: {message}")


class RobotRuntimeError(InterpreterError):
    def __init__(self, message: str, line: int, state: SceneState):
        self.message = message
        self.line = line
        self.state = state
        super().__init__(f"line {line}: {message}")


class ExecutionLimitError(RobotRuntimeError):
    """Raised when a program does not stop within the instruction limit."""


class _Operation(Enum):
    FORWARD = auto()
    LEFT = auto()
    RIGHT = auto()
    LAY = auto()
    TAKE = auto()
    END = auto()
    REPEAT = auto()


@dataclass(frozen=True, slots=True)
class _Instruction:
    operation: _Operation
    line: int
    repeat_count: int | None = None


_COMMANDS = {
    "krok": _Operation.FORWARD,
    "dolava": _Operation.LEFT,
    "doprava": _Operation.RIGHT,
    "poloz": _Operation.LAY,
    "zober": _Operation.TAKE,
}


def _normalize(value: str) -> str:
    return value.lower().translate(_DIACRITICS)


def _snapshot(grid: list[int], robot_x: int, robot_y: int, direction: int) -> SceneState:
    rows = tuple(
        tuple(grid[y * GRID_SIZE : (y + 1) * GRID_SIZE])
        for y in range(GRID_SIZE)
    )
    return SceneState(rows, robot_x, robot_y, direction)


def _parse(source: str) -> list[_Instruction]:
    instructions: list[_Instruction] = []
    open_repeats = 0

    for line_number, raw_line in enumerate(source.split("\n"), start=1):
        position = 0
        while position < len(raw_line) and raw_line[position] in _WHITESPACE:
            position += 1
        if position == len(raw_line) or raw_line[position] == "#":
            continue

        def read_word(word: str) -> bool:
            nonlocal position
            end = position + len(word)
            if _normalize(raw_line[position:end]) != word:
                return False
            next_character = _normalize(raw_line[end : end + 1])
            if next_character and "a" <= next_character <= "z":
                return False
            position = end
            while position < len(raw_line) and raw_line[position] in _WHITESPACE:
                position += 1
            return True

        operation = next(
            (operation for word, operation in _COMMANDS.items() if read_word(word)),
            None,
        )
        if operation is not None:
            if position != len(raw_line):
                raise ParseError("po príkaze musí nasledovať nový riadok", line_number)
            instructions.append(_Instruction(operation, line_number))
            continue

        if read_word("opakuj"):
            number_start = position
            while position < len(raw_line) and "0" <= raw_line[position] <= "9":
                position += 1
            if position == number_start:
                raise ParseError(
                    "po 'opakuj' musí nasledovať číslo: počet opakovaní",
                    line_number,
                )
            repeat_count = int(raw_line[number_start:position])
            if position != len(raw_line):
                raise ParseError("po príkaze musí nasledovať nový riadok", line_number)
            instructions.append(
                _Instruction(_Operation.REPEAT, line_number, repeat_count)
            )
            open_repeats += 1
            continue

        if read_word("koniec"):
            if position != len(raw_line):
                raise ParseError("po príkaze musí nasledovať nový riadok", line_number)
            if open_repeats == 0:
                raise ParseError("nie je žiadne otvorené opakovanie", line_number)
            instructions.append(_Instruction(_Operation.END, line_number))
            open_repeats -= 1
            continue

        raise ParseError("neznámy príkaz", line_number)

    if open_repeats:
        line_number = max(1, len(source.split("\n")))
        raise ParseError("neukončené opakovanie", line_number)

    return instructions


def interpret(source: str, *, max_steps: int = 1_000_000) -> SceneState:
    """Run ``source`` and return the scene after the program stops.

    Syntax errors raise :class:`ParseError`. Runtime errors raise
    :class:`RobotRuntimeError`; its ``state`` attribute contains the scene at
    the failed instruction. ``max_steps`` bounds programs such as
    ``opakuj 0``, which never terminate in the browser interpreter.
    """

    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if max_steps < 1:
        raise ValueError("max_steps must be at least 1")

    program = _parse(source)
    grid = [0] * (GRID_SIZE * GRID_SIZE)
    robot_x = START_X
    robot_y = START_Y
    robot_direction = START_DIRECTION
    repeat_jumps: list[int] = []
    repeat_counts: list[int] = []
    program_counter = 0
    steps = 0

    def fail(message: str, line: int) -> None:
        raise RobotRuntimeError(
            message,
            line,
            _snapshot(grid, robot_x, robot_y, robot_direction),
        )

    while program_counter < len(program):
        instruction = program[program_counter]
        if steps >= max_steps:
            raise ExecutionLimitError(
                f"program prekročil limit {max_steps} inštrukcií",
                instruction.line,
                _snapshot(grid, robot_x, robot_y, robot_direction),
            )
        steps += 1

        front_x = robot_x + _DIRECTION_X[robot_direction]
        front_y = robot_y + _DIRECTION_Y[robot_direction]
        operation = instruction.operation

        if operation is _Operation.FORWARD:
            if not (0 <= front_x < GRID_SIZE and 0 <= front_y < GRID_SIZE):
                fail("nemôžem sa pohnúť von z poľa", instruction.line)
            robot_height = grid[GRID_SIZE * robot_y + robot_x]
            front_height = grid[GRID_SIZE * front_y + front_x]
            if front_height - robot_height > 1:
                fail("nemôžem vyskočiť tak vysoko", instruction.line)
            if front_height - robot_height < -1:
                fail("nemôžem zoskočiť tak nízko", instruction.line)
            robot_x = front_x
            robot_y = front_y
        elif operation is _Operation.LEFT:
            robot_direction = (robot_direction + 1) % 4
        elif operation is _Operation.RIGHT:
            robot_direction = (robot_direction + 3) % 4
        elif operation is _Operation.LAY:
            if not (0 <= front_x < GRID_SIZE and 0 <= front_y < GRID_SIZE):
                fail("nemôžem položiť tehlu von z poľa", instruction.line)
            robot_height = grid[GRID_SIZE * robot_y + robot_x]
            front_height = grid[GRID_SIZE * front_y + front_x]
            if front_height - robot_height > 1:
                fail("nemôžem položiť tehlu tak ďaleko nad seba", instruction.line)
            if front_height - robot_height < -1:
                fail("nemôžem položiť tehlu tak ďaleko pod seba", instruction.line)
            grid[GRID_SIZE * front_y + front_x] += 1
        elif operation is _Operation.TAKE:
            if not (0 <= front_x < GRID_SIZE and 0 <= front_y < GRID_SIZE):
                fail("nemám pred sebou žiadnu tehlu", instruction.line)
            robot_height = grid[GRID_SIZE * robot_y + robot_x]
            front_height = grid[GRID_SIZE * front_y + front_x]
            if front_height - robot_height > 2:
                fail("nemôžem zobrať tehlu tak zďaleka nad sebou", instruction.line)
            if front_height - robot_height < 0:
                fail("nemôžem zobrať tehlu tak zďaleka pod sebou", instruction.line)
            if front_height == 0:
                fail("nemám pred sebou žiadnu tehlu", instruction.line)
            grid[GRID_SIZE * front_y + front_x] -= 1
        elif operation is _Operation.REPEAT:
            repeat_jumps.append(program_counter)
            repeat_counts.append(instruction.repeat_count or 0)
        else:
            repeat_counts[-1] -= 1
            if repeat_counts[-1] == 0:
                repeat_counts.pop()
                repeat_jumps.pop()
            else:
                program_counter = repeat_jumps[-1]

        program_counter += 1

    return _snapshot(grid, robot_x, robot_y, robot_direction)
