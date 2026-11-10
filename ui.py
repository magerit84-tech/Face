"""화면 표현 전용 헬퍼: 커스텀 CSS, 히어로, 결과 섹션 파싱, 별점 렌더링."""

import html
import re

# 금색 포인트는 라이트/다크 모두에서 쓰이므로 배경과 상관없이 대비가 나오는 값만 사용.
# 카드 배경은 반투명이라 어느 테마 위에서도 자연스럽게 섞인다. 글자색은 테마 textColor를 그대로 상속.
CUSTOM_CSS = """
<style>
.hero {
  text-align: center;
  padding: 2.2rem 1.2rem 1.8rem;
  margin-bottom: 1.2rem;
  border-radius: 1.2rem;
  background: radial-gradient(circle at 50% 0%, #4B2C83 0%, #241C55 55%, #12102A 100%);
  border: 1px solid rgba(212, 175, 55, 0.55);
  box-shadow: 0 8px 28px rgba(18, 16, 42, 0.35);
}
.hero .hero-icon { font-size: 3rem; line-height: 1; }
.hero h1 {
  font-family: serif;
  color: #F5D77A !important;
  font-size: clamp(2rem, 8vw, 2.8rem);
  margin: 0.4rem 0 0.2rem;
  padding: 0;
  letter-spacing: 0.08em;
}
/* 제목에 마우스를 올렸을 때 나타나는 앵커 링크 아이콘 숨김 */
.hero [data-testid="stHeaderActionElements"], .hero h1 a { display: none !important; }
.hero p { color: #EDE6F7; margin: 0 0 0.9rem; font-size: 1.05rem; }
.hero .badge {
  display: inline-block;
  padding: 0.3rem 0.85rem;
  border-radius: 999px;
  background: rgba(212, 175, 55, 0.18);
  border: 1px solid rgba(212, 175, 55, 0.6);
  color: #F5D77A;
  font-size: 0.82rem;
}

/* 결과 카드: st.container(key="card-...")에 적용 */
[class*="st-key-card-"] {
  background: rgba(127, 96, 200, 0.08);
  border: 1px solid rgba(212, 175, 55, 0.45);
  border-radius: 1rem;
  padding: 1.1rem 1.2rem;
  box-shadow: 0 4px 18px rgba(18, 16, 42, 0.12);
}
.st-key-card-first {
  background: linear-gradient(135deg, rgba(212, 175, 55, 0.16), rgba(127, 96, 200, 0.14));
  border-width: 2px;
}
.card-title {
  font-family: serif;
  font-size: 1.25rem;
  font-weight: 700;
  margin: 0 0 0.35rem;
}

/* 미리보기 이미지 */
.preview { text-align: center; margin: 0.8rem 0 0.4rem; }
.preview img {
  max-width: min(300px, 100%);
  border-radius: 1rem;
  border: 2px solid rgba(212, 175, 55, 0.7);
  box-shadow: 0 6px 20px rgba(18, 16, 42, 0.25);
}
.preview .cap { font-size: 0.85rem; opacity: 0.7; margin-top: 0.35rem; }

/* 관상 보기 버튼 강조 */
.st-key-analyze button {
  background: linear-gradient(135deg, #D4AF37, #B8860B) !important;
  color: #1F1A3D !important;
  border: none !important;
  font-weight: 700;
  font-size: 1.1rem;
  padding: 0.7rem 1rem;
  box-shadow: 0 4px 14px rgba(212, 175, 55, 0.4);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.st-key-analyze button p { font-size: 1.1rem; font-weight: 700; }
.st-key-analyze button:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(212, 175, 55, 0.55);
}
.st-key-analyze button:disabled { opacity: 0.45; box-shadow: none; }

/* 운세 별점 */
.scores {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.6rem;
}
.score-item {
  text-align: center;
  padding: 0.6rem 0.3rem;
  border-radius: 0.75rem;
  background: rgba(212, 175, 55, 0.10);
}
.score-item .label { font-size: 0.9rem; opacity: 0.85; }
.score-item .stars { font-size: 1.25rem; letter-spacing: 0.08em; color: #D4AF37; white-space: nowrap; }
.score-item .stars .off { color: rgba(140, 130, 170, 0.45); }
@media (min-width: 640px) {
  .scores { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}

.footer-note { text-align: center; font-size: 0.8rem; opacity: 0.6; margin-top: 2rem; }
</style>
"""

HERO_HTML = """
<div class="hero">
  <div class="hero-icon">🔮</div>
  <h1>AI 관상가</h1>
  <p>사진 한 장으로 보는 나의 관상</p>
  <span class="badge">⚠️ 재미로만 봐주세요 · 사진은 저장되지 않습니다</span>
</div>
"""

SCORE_ICONS = {"재물": "💰 재물운", "애정": "💕 애정운", "직업": "💼 직업운", "건강": "🌿 건강운"}

# 섹션 키 → 응답 헤더에서 찾을 키워드
SECTION_KEYWORDS = {
    "first": "첫인상",
    "parts": "부위별",
    "fortune": "종합",
    "animal": "동물상",
    "advice": "개운",
}


def preview_html(data_url: str) -> str:
    return (
        f'<div class="preview"><img src="{data_url}" alt="분석할 사진">'
        '<div class="cap">분석할 사진</div></div>'
    )


def scores_html(scores: dict[str, int]) -> str:
    items = []
    for key, label in SCORE_ICONS.items():
        if key not in scores:
            continue
        n = scores[key]
        stars = "★" * n + f'<span class="off">{"★" * (5 - n)}</span>'
        items.append(
            f'<div class="score-item"><div class="label">{label}</div>'
            f'<div class="stars" aria-label="{label} 5점 만점에 {n}점">{stars}</div></div>'
        )
    return f'<div class="scores">{"".join(items)}</div>'


def card_title(text: str) -> str:
    return f'<div class="card-title">{html.escape(text)}</div>'


def split_sections(body: str) -> tuple[dict[str, tuple[str, str]], str]:
    """응답 본문을 '## ' 헤더 단위로 나눈다.

    Returns:
        ({섹션키: (헤더 텍스트, 내용)}, 어느 섹션에도 속하지 않은 나머지 텍스트)
    """
    sections: dict[str, tuple[str, str]] = {}
    leftovers: list[str] = []
    chunks = re.split(r"^##(?!#)\s*", body, flags=re.MULTILINE)
    if chunks and chunks[0].strip():
        leftovers.append(chunks[0].strip())
    for chunk in chunks[1:]:
        heading, _, content = chunk.partition("\n")
        heading = heading.strip()
        key = next((k for k, kw in SECTION_KEYWORDS.items() if kw in heading and k not in sections), None)
        if key:
            sections[key] = (heading, content.strip())
        else:
            leftovers.append(f"## {chunk.strip()}")
    return sections, "\n\n".join(leftovers)


def split_parts(content: str) -> tuple[str, list[tuple[str, str]]]:
    """'부위별 관상' 내용을 '### ' 소제목 단위로 나눈다. (머리말, [(소제목, 내용)])"""
    chunks = re.split(r"^###\s*", content, flags=re.MULTILINE)
    intro = chunks[0].strip()
    parts = []
    for chunk in chunks[1:]:
        title, _, text = chunk.partition("\n")
        parts.append((title.strip(), text.strip()))
    return intro, parts
