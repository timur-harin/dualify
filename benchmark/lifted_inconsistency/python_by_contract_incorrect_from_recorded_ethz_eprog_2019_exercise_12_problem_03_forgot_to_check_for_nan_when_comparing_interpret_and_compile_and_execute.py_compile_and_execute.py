# Compile and execute the given ``program``.
def compile_and_execute(
    program: problem_01.Program,
) -> MutableMapping[problem_01.Identifier, float]:
    """Compile and execute the given ``program``."""
    instructions = compile_program(program)
    return execute(instructions)
