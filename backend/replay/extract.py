"""ReplaySpanLLM: the extraction model call, recorded once and replayed on stage."""

from backend.extract import llm as llm_module
from backend.replay import cache
from contracts.schemas import Case

COMPONENT = "extract"


class ReplaySpanLLM:
    """Wraps AnthropicSpanLLM. The live client is only built when a live call is made."""

    def __init__(self, inner=None) -> None:
        self._inner = inner
        self.model = getattr(inner, "model", llm_module.AnthropicSpanLLM.model)
        self.error: str | None = None

    def _live(self):
        if self._inner is None:
            self._inner = llm_module.AnthropicSpanLLM()
        return self._inner

    def key(self, new_text: str, case: Case) -> str:
        item = case.line_item
        text = f"{item.product}\n{item.dosage_form}\n{new_text}"
        return cache.make_key(COMPONENT, self.model, llm_module.PROMPT_VERSION, text)

    def find_spans(self, new_text: str, case: Case) -> dict:
        self.error = None
        current = cache.mode()
        if current == cache.LIVE:
            spans = self._live().find_spans(new_text, case)
            self.error = getattr(self._inner, "error", None)
            return spans
        key = self.key(new_text, case)
        if current == cache.REPLAY:
            out = cache.load(COMPONENT, key)
            self.error = out.get("error")
            return llm_module.sanitise_spans(out["spans"])
        spans = self._live().find_spans(new_text, case)
        self.error = getattr(self._inner, "error", None)
        cache.save(
            COMPONENT, key, model=self.model, prompt_version=llm_module.PROMPT_VERSION,
            output={"spans": spans, "error": self.error},
        )
        return spans
