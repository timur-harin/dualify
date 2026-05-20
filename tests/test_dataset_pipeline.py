from pathlib import Path

from dualify.dataset_pipeline import run_dataset_pipeline


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_dataset_pipeline_preview_and_clean(tmp_path: Path) -> None:
    pbc = tmp_path / "pbc"
    crosshair = tmp_path / "crosshair"
    out_dir = tmp_path / "out"

    _write(
        pbc / "sample.py",
        """
import icontract
from icontract import require, ensure

@icontract.require(lambda a: a > 0)
@icontract.ensure(lambda result, a: result >= a)
def inc_attr(a: int) -> int:
    return a + 1

@require(lambda x: x > 0)
@ensure(lambda result, x: result >= x)
def inc_bare(x: int) -> int:
    return x + 1
""".strip(),
    )

    _write(
        crosshair / "ex.py",
        '''
def is_even(x: int) -> bool:
    """
    pre: x >= 0
    post: ret == (x % 2 == 0)
    """
    return x % 2 == 0
'''.strip(),
    )

    preview = run_dataset_pipeline(
        python_by_contract_path=str(pbc),
        crosshair_examples_path=str(crosshair),
        output_dir=str(out_dir),
        apply_cleaning=False,
    )
    assert preview["status"] == "awaiting_cleaning_confirmation"

    final = run_dataset_pipeline(
        python_by_contract_path=str(pbc),
        crosshair_examples_path=str(crosshair),
        output_dir=str(out_dir),
        apply_cleaning=True,
    )
    assert final["status"] == "cleaning_completed"
    assert final["summary"]["raw_total"] >= 3
    assert final["summary"]["clean_total"] >= 2
