"""Every control on the order form sends its value somewhere.

This is the test that did not exist, and the defect it would have caught was
measured rather than suspected. `apps/web/app/page.tsx` offered a material picker —
Алюминий / Сталь / Полимер — which changed the colour of the 3D preview and nothing
else. `grep -rn material apps/api/app/` finds nothing: the value never reached the
API, never reached the worker, never reached a manifest. A visitor picked "Сталь"
and had every reason to believe they had ordered a steel part.

Three more of the same shape were on the page beside it: a "Точность построения"
segmented control that changed one word in a summary and nothing in the build, a
"Тип модели" dropdown that was a `<button>` with one option and no handler, and a
thousand-character "Пожелания" box whose text went into `localStorage` and nowhere.

The check lives here rather than in a JavaScript test runner because there is no
JavaScript test runner in this repository, and adding one to hold a single
assertion is a larger change than the assertion is worth. What it reads is the
source, which is what a reviewer would read.

It is deliberately brittle: a new control that binds state has to be either sent or
listed below with a reason. That is the whole point — the previous arrangement was
one where adding a control that goes nowhere costs nothing and is invisible.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PAGE = Path(__file__).parents[3] / "apps" / "web" / "app" / "page.tsx"

#: `const [x, setX] = useState(...)`, which is every piece of state the page holds.
STATE = re.compile(r"const \[(\w+), set\w+\] = useState")

#: State that is deliberately not sent, each with the reason it is allowed to stay.
#:
#: Every entry here is a claim somebody has to defend at review. An entry with a
#: vague reason is the thing this test exists to make visible.
LOCAL_ONLY: dict[str, str] = {
    # Presentation and transport state, which nothing outside the browser wants.
    "showLanding": "which of the two pages is being shown",
    "file": "the upload itself, sent as the request body rather than as a field",
    "sourceUrl": "an object URL for the local preview of that file",
    "orderId": "the id the API returned; sent in the path of every later request",
    "order": "the API's own answer, held for rendering",
    "viewMode": "which of the model and the drawing the viewer shows",
    "busy": "whether a request is in flight",
    "dragging": "whether a file is being dragged over the drop zone",
    "error": "the message being shown",
    "measured": "read out of the delivered validation report",
    "confirmed": "the sizes the visitor confirmed, shown until a model is measured",
    "authChecked": "whether /auth/me has answered yet",
    "authMode": "which of sign-in and register the form is showing",
    # Answers are sent, but through their own request rather than with the upload.
    "answers": "sent to /drawing-jobs/{id}/answers",
    # Credentials, which travel as cookies and headers rather than in a body.
    "token": "the operator's diagnostic key, sent as a header",
    "session": "who is signed in; the CSRF token from it is sent as a header",
    "authEmail": "sent to /auth/sign-in and /auth/register",
    "authPassword": "sent to /auth/sign-in and /auth/register",
    "authTotp": "sent to /auth/sign-in",
    # Whether the sign-in form is showing the second-factor field at all. Purely a
    # browser decision: only operators and administrators have a second factor, and
    # the API answers a missing code and a wrong password with the same words on
    # purpose, so nothing can be asked of it to decide this. A customer never meets
    # the field; an operator asks for it with a click that discloses nothing.
    "staffSignIn": "whether the second-factor field is shown; decided in the browser",
    # The one control that is genuinely local and is labelled as such.
    #
    # It decides which of the delivered files the download button hands over, and
    # every build produces all three regardless — the STEP and the STL because
    # ADR-023 says those are the product, and the report because it is what the
    # model was checked against. The page says "Что скачать" rather than "Форматы
    # результата", which is the difference between describing a filter and
    # implying an order.
    "outputs": "a download filter; all three artifacts are produced either way",
}


#: `/* … */`, `{/* … */}` and `// …`.
COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


def page_source() -> str:
    return PAGE.read_text(encoding="utf-8")


def code_only(source: str) -> str:
    """The source with its comments removed.

    Needed by the assertions below rather than by the ones above, and the reason is
    worth a line: each removal on that page carries a comment naming what was
    removed and why — "Материал", "Пожелания", the material picker — which is
    exactly the record this repository wants kept. A test that greps the raw file
    for those words is a test that fails *because* the explanation is there.
    """
    return COMMENT.sub(" ", source)


def test_the_page_is_where_this_test_thinks_it_is():
    """A scan that found nothing would pass every assertion below."""
    assert PAGE.exists(), PAGE
    assert len(STATE.findall(page_source())) > 5


@pytest.mark.parametrize("name", sorted(STATE.findall(page_source())))
def test_every_piece_of_form_state_is_sent_or_declared_local(name: str):
    source = page_source()
    if name in LOCAL_ONLY:
        return
    # Sent means the identifier appears inside something being serialised or handed
    # to `fetch`. Crude on purpose: the alternative is parsing TypeScript, and what
    # this needs to catch is a value that appears in no request at all.
    sent = re.search(
        rf"(JSON\.stringify\([^)]*\b{name}\b|body:[^;]*\b{name}\b|"
        rf"headers[^;]*\b{name}\b|api\([^)]*\b{name}\b)",
        source,
        re.DOTALL,
    )
    assert sent, (
        f"`{name}` is bound to a control and its value reaches no request. "
        "Either send it, or add it to LOCAL_ONLY with the reason it stays — a "
        "control that decides nothing is a promise the service does not keep."
    )


def test_the_controls_that_went_nowhere_are_gone():
    """Named rather than implied, so a revert is loud.

    Each of these was on the page, each looked like a choice, and none of them
    reached the API. They are listed by name because "the material picker was
    removed" in a commit message is not something a test can hold to.
    """
    source = code_only(page_source())
    # The explanation of each removal stays in the file, so this reads the code
    # rather than the prose: no state, no handler, no binding.
    for gone in ("setMaterial", "setPrecision", "setComment", "materialOptions"):
        assert gone not in source, f"{gone} is back"
    assert "Пожелания" not in source
    assert "Материал</span>" not in source


def test_the_landing_page_does_not_score_what_it_cannot_measure():
    """"100% контроль ключевых размеров" was a percentage nothing backs.

    What the service can back is the mechanism: every dimension the document
    declares is measured on the exported file, and the reading is compared against
    the compilation. Neither is 100% of anything — a drawing misread the same way
    twice satisfies both — so the claim names what happens instead of scoring it.
    """
    landing = (PAGE.parent / "landing-page.tsx").read_text(encoding="utf-8")

    assert "100%" not in code_only(landing)
    assert "измеряется на готовом файле" in landing
