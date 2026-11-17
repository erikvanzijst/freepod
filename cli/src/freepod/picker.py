"""An interactive pick from a list: arrows move, typing narrows, Enter picks."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, TypeVar

T = TypeVar("T")


def pick(
    items: Sequence[T],
    labels: Sequence[str],
    *,
    title: str,
    empty: str,
    input: Any = None,
    output: Any = None,
) -> Optional[T]:
    """Let the user pick one item by its label. Returns None on Escape or Ctrl-C."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl

    rows = list(zip(items, labels))
    query = Buffer(multiline=False)
    state = {"index": 0}

    def shown() -> List[Any]:
        text = query.text.strip().lower()
        return [row for row in rows if text in row[1].lower()]

    def render() -> List[Any]:
        visible = shown()
        state["index"] = min(state["index"], max(len(visible) - 1, 0))
        if not visible:
            return [("italic", f"  {empty}\n")]
        return [
            (
                "reverse" if i == state["index"] else "",
                f"{'>' if i == state['index'] else ' '} {label}\n",
            )
            for i, (_item, label) in enumerate(visible)
        ]

    query.on_text_changed += lambda _buffer: state.update(index=0)
    keys = KeyBindings()

    @keys.add("up")
    def _up(_event: Any) -> None:
        state["index"] = max(state["index"] - 1, 0)

    @keys.add("down")
    def _down(_event: Any) -> None:
        state["index"] = min(state["index"] + 1, max(len(shown()) - 1, 0))

    @keys.add("enter")
    def _enter(event: Any) -> None:
        visible = shown()
        if visible:
            event.app.exit(result=visible[state["index"]][0])

    @keys.add("escape", eager=True)
    @keys.add("c-c")
    def _cancel(event: Any) -> None:
        event.app.exit(result=None)

    layout = Layout(
        HSplit(
            [
                Window(FormattedTextControl(title), height=1),
                Window(BufferControl(buffer=query), height=1),
                Window(FormattedTextControl(render)),
            ]
        )
    )
    app: Application[Optional[T]] = Application(
        layout=layout, key_bindings=keys, input=input, output=output, erase_when_done=True
    )
    return app.run()
