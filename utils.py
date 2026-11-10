"""이미지 전처리, 설정 로딩, OpenAI 호출 유틸리티."""

import base64
import io
import os
import re

import openai
import streamlit as st
from dotenv import load_dotenv
from PIL import Image, ImageOps, UnidentifiedImageError

from prompts import DEFAULT_STYLE, NO_FACE_TOKEN, STYLE_PROMPTS, SYSTEM_PROMPT, USER_PROMPT

load_dotenv()

DEFAULT_MODEL = "gpt-4o-mini"
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10MB
MAX_SIDE = 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}  # MPO: 일부 휴대폰 JPEG
SCORE_LABELS = ("재물", "애정", "직업", "건강")


class AnalysisError(Exception):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담은 예외."""


def _get_setting(name: str) -> str | None:
    """st.secrets → 환경변수(.env) 순서로 설정값을 읽는다."""
    try:
        value = st.secrets.get(name)
    except Exception:  # secrets.toml이 없거나 파싱 실패 (StreamlitSecretNotFoundError 등)
        value = None
    if not value:
        value = os.getenv(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def get_api_key() -> str | None:
    """OpenAI API 키를 반환한다. st.secrets → .env 순서, 없으면 None."""
    return _get_setting("OPENAI_API_KEY")


def get_model_name() -> str:
    """사용할 OpenAI 모델명을 반환한다. 없으면 gpt-4o-mini."""
    return _get_setting("OPENAI_MODEL") or DEFAULT_MODEL


def preprocess_image(uploaded_file) -> str:
    """업로드된 이미지를 리사이즈·JPEG 압축 후 base64 data URL로 반환한다.

    디스크에 저장하지 않고 메모리에서만 처리한다.

    Raises:
        ValueError: 10MB 초과이거나 지원하지 않는 이미지 형식인 경우.
    """
    data = uploaded_file.getvalue()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("사진 용량이 10MB를 넘습니다. 더 작은 사진을 올려주세요.")

    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("이미지 파일을 읽을 수 없습니다. JPG, PNG, WEBP 사진을 올려주세요.") from e
    if fmt not in ALLOWED_FORMATS:
        raise ValueError("지원하지 않는 형식입니다. JPG, PNG, WEBP 사진을 올려주세요.")

    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        # 투명 배경은 흰색으로 채운다
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.getchannel("A"))
            img = bg
        else:
            img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _create_completion(client: openai.OpenAI, model: str, messages: list, use_temperature: bool):
    kwargs = {"model": model, "messages": messages, "max_completion_tokens": 1500}
    if use_temperature:
        kwargs["temperature"] = 0.8
    return client.chat.completions.create(**kwargs)


def analyze_face(image_data_url: str, style: str = DEFAULT_STYLE) -> str:
    """OpenAI 비전 모델로 관상을 분석하고 응답 원문(Markdown)을 반환한다.

    Raises:
        AnalysisError: API 키 누락, 인증·한도·네트워크 오류 등 (한국어 메시지 포함).
    """
    api_key = get_api_key()
    if not api_key:
        raise AnalysisError("OpenAI API 키가 설정되지 않았습니다.")

    client = openai.OpenAI(api_key=api_key, timeout=60)
    model = get_model_name()
    style_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS[DEFAULT_STYLE])
    messages = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{style_prompt}"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": USER_PROMPT},
                {"type": "image_url", "image_url": {"url": image_data_url, "detail": "high"}},
            ],
        },
    ]

    try:
        try:
            response = _create_completion(client, model, messages, use_temperature=True)
        except openai.BadRequestError as e:
            # 일부 추론 모델은 temperature 지정을 허용하지 않으므로 빼고 재시도
            if "temperature" not in str(e):
                raise
            response = _create_completion(client, model, messages, use_temperature=False)
    except openai.AuthenticationError as e:
        raise AnalysisError("API 키가 올바르지 않습니다. 키를 다시 확인해 주세요.") from e
    except openai.RateLimitError as e:
        raise AnalysisError(
            "요청 한도를 초과했거나 크레딧이 부족합니다. 잠시 후 다시 시도하거나 OpenAI 결제 상태를 확인해 주세요."
        ) from e
    except openai.APITimeoutError as e:
        raise AnalysisError("응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.") from e
    except openai.APIConnectionError as e:
        raise AnalysisError("OpenAI 서버에 연결할 수 없습니다. 인터넷 연결을 확인해 주세요.") from e
    except openai.NotFoundError as e:
        raise AnalysisError(f"모델 '{model}'을(를) 사용할 수 없습니다. OPENAI_MODEL 설정을 확인해 주세요.") from e
    except openai.APIError as e:
        raise AnalysisError("관상 분석 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.") from e

    choice = response.choices[0]
    content = (choice.message.content or "").strip()
    if not content:
        if choice.finish_reason == "length":
            # 추론형 모델은 출력 한도를 내부 추론에 다 써서 빈 응답을 돌려줄 수 있음
            raise AnalysisError(
                f"모델 '{model}'의 응답이 출력 한도에 걸려 비어 있습니다. "
                "다시 시도하거나, 추론형 모델이라면 OPENAI_MODEL을 일반 모델(예: gpt-4o-mini)로 바꿔 주세요."
            )
        raise AnalysisError("관상가가 이 사진에 대한 풀이를 하지 못했습니다. 다른 사진으로 시도해 주세요.")
    return content


_NO_FACE_RE = re.compile(rf"\W*{NO_FACE_TOKEN}\W*", re.IGNORECASE)


def is_no_face(text: str) -> bool:
    """응답이 얼굴 없음 신호인지 판단. `NO_FACE.`, **NO_FACE**, 백틱 등 장식이 붙어도 인식."""
    return bool(_NO_FACE_RE.fullmatch(text.strip()))


_SCORES_LINE = re.compile(r"^\W*SCORES\s*[:：]\s*(.+?)\W*$", re.IGNORECASE)
_SCORE_ITEM = re.compile(r"(재물|애정|직업|건강)\s*[=:：]\s*(\d)")


def split_scores(text: str) -> tuple[str, dict[str, int]]:
    """응답에서 SCORES 줄을 제거하고 (본문, {재물: n, ...})을 반환한다.

    파싱에 실패하면 점수는 빈 dict로 반환하며 예외를 던지지 않는다.
    """
    scores: dict[str, int] = {}
    kept_lines = []
    for line in text.splitlines():
        m = _SCORES_LINE.match(line.strip())
        if m:
            for label, value in _SCORE_ITEM.findall(m.group(1)):
                scores[label] = min(5, max(1, int(value)))
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip(), scores
