"""Every lump of material in the part, by the name the document gave it.

Before CAD-IR 1.7 the engine kept one running solid, so `source_body` — in the
contract since 1.1 — pointed at the only thing there was and could be ignored. This
is the table that makes it mean something, and it is deliberately small: a list of
bodies, the names each answers to, and which one is active.

Two rules.

**The active body is the last one created or modified.** A feature that names no
`source_body` targets it, which is exactly what every document written before 1.7
means: a boss fuses into the plate because the plate is what is being built.

**A name is never reused for a different body.** The document's `produces` entries are
the names, and a boolean that consumes a tool removes the tool's body along with its
names, so a later selector naming it fails rather than resolving to whatever took its
place.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import CadEngineError


@dataclass
class Body:
    """One solid, and every name the document can call it by."""

    solid: object
    names: set[str] = field(default_factory=set)


class Bodies:
    """The part, as the document's own bodies rather than as one solid."""

    def __init__(self) -> None:
        self._bodies: list[Body] = []
        self._active: int | None = None

    # --- reading ----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._bodies)

    @property
    def empty(self) -> bool:
        return not self._bodies

    def solid_at(self, index: int | None):
        return None if index is None else self._bodies[index].solid

    def find(self, name: str):
        """The solid a name refers to, or nothing. Never raises: callers differ."""
        for body in self._bodies:
            if name in body.names:
                return body.solid
        return None

    def locate(self, name: str | None, what: str) -> int | None:
        """Which body a feature means: the one it named, or the active one.

        `None` comes back only when nothing has been built at all, which is a
        different failure from naming a body that does not exist — one is a document
        with no base feature, the other is a document naming something it never made.
        """
        if name is None:
            return self._active
        for index, body in enumerate(self._bodies):
            if name in body.names:
                return index
        raise CadEngineError(
            "FEATURE_RESULT_UNAVAILABLE",
            "feature",
            f"{what} names the body {name}, which nothing has built. "
            f"{self._known()}",
        )

    def _known(self) -> str:
        names = sorted(name for body in self._bodies for name in body.names)
        if not names:
            return "No body has been built yet."
        return "Bodies so far: " + ", ".join(names) + "."

    # --- writing ----------------------------------------------------------

    def create(self, solid, names: set[str]) -> int:
        for name in names:
            if self.find(name) is not None:
                raise CadEngineError(
                    "CAD_IR_INVALID",
                    "feature",
                    f"Two bodies are both called {name}.",
                )
        self._bodies.append(Body(solid=solid, names=set(names)))
        self._active = len(self._bodies) - 1
        return self._active

    def replace(self, index: int, solid) -> None:
        self._bodies[index].solid = solid
        self._active = index

    def alias(self, index: int, names: set[str]) -> None:
        """Let a body answer to another name as well.

        A feature that adds to a body may declare a result of its own, and that name
        refers to the body it added to. Aliasing rather than renaming: the plate is
        still `body.main` after a boss has been welded to it.
        """
        self._bodies[index].names |= set(names)

    def drop(self, index: int) -> None:
        del self._bodies[index]
        if self._active is not None and self._active >= len(self._bodies):
            self._active = len(self._bodies) - 1 if self._bodies else None

    # --- the finished part ------------------------------------------------

    def result(self):
        """One solid, or a compound of everything that is left.

        A compound rather than a fused solid: bodies that were never combined are
        separate on purpose, and fusing them here to make the export simpler would be
        the engine overruling the document. STEP carries several solids and the
        verifier counts them, which is what `body_count` is for.
        """
        if not self._bodies:
            raise CadEngineError(
                "UNSUPPORTED_FEATURE_SET", "prepare", "The document builds no solid."
            )
        if len(self._bodies) == 1:
            return self._bodies[0].solid
        from build123d import Compound

        return Compound(children=[body.solid for body in self._bodies])

    def names(self) -> list[list[str]]:
        """Every body's names, in creation order. For diagnostics and tests."""
        return [sorted(body.names) for body in self._bodies]


__all__ = ["Bodies", "Body"]
