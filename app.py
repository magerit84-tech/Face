"""AI 관상가 - Streamlit 메인 앱."""

import streamlit as st

import ui
from prompts import DEFAULT_STYLE, STYLE_PROMPTS
from utils import AnalysisError, analyze_face, get_api_key, is_no_face, preprocess_image, split_scores

MAX_ANALYSES_PER_SESSION = 5

st.set_page_config(page_title="AI 관상가", page_icon="🔮", layout="centered")
st.markdown(ui.CUSTOM_CSS, unsafe_allow_html=True)

# ---- 세션 상태 ----
st.session_state.setdefault("analysis_count", 0)
st.session_state.setdefault("result", None)  # {"body", "scores", "style"} | {"no_face"} | {"error"}
st.session_state.setdefault("input_key", 0)  # 바꾸면 업로더/카메라가 초기화됨
st.session_state.setdefault("active_source", "upload")  # 가장 최근에 바뀐 입력: "upload" | "camera"


def reset():
    st.session_state.result = None
    st.session_state.input_key += 1


def on_image_change(source: str):
    # 사진이 바뀌면 이전 사진의 결과는 더 이상 맞지 않으므로 지우고, 최근 입력을 우선 사용
    st.session_state.active_source = source
    st.session_state.result = None


# ---- 사이드바 ----
with st.sidebar:
    st.header("⚙️ 설정")
    style = st.radio("분석 스타일", list(STYLE_PROMPTS.keys()), index=list(STYLE_PROMPTS).index(DEFAULT_STYLE))
    st.divider()
    st.header("📖 사용 안내")
    st.markdown(
        "1. 얼굴이 정면으로 잘 보이는 사진을 올리거나 촬영하세요.\n"
        "2. **관상 보기** 버튼을 누르세요.\n"
        "3. 관상가의 풀이를 확인하고 결과를 저장할 수 있어요.\n\n"
        f"- 한 세션당 최대 **{MAX_ANALYSES_PER_SESSION}회** 분석할 수 있어요.\n"
        "- 본인 또는 동의를 받은 사진만 올려주세요."
    )
    remaining = MAX_ANALYSES_PER_SESSION - st.session_state.analysis_count
    st.caption(f"남은 분석 횟수: {max(0, remaining)}회")

# ---- 헤더 ----
st.markdown(ui.HERO_HTML, unsafe_allow_html=True)

if not get_api_key():
    st.error(
        "OpenAI API 키가 설정되지 않았습니다.\n\n"
        "- **로컬**: 프로젝트 폴더의 `.env` 파일에 `OPENAI_API_KEY=sk-...`를 입력하세요.\n"
        "- **Streamlit Cloud**: 앱 설정 → Secrets에 `OPENAI_API_KEY = \"sk-...\"`를 입력하세요."
    )
    st.stop()

# ---- 이미지 입력 ----
tab_upload, tab_camera = st.tabs(["📁 사진 업로드", "📷 카메라 촬영"])
with tab_upload:
    uploaded = st.file_uploader(
        "얼굴이 잘 보이는 사진을 올려주세요 (JPG, PNG, WEBP · 최대 10MB)",
        type=["jpg", "jpeg", "png", "webp"],
        key=f"uploader_{st.session_state.input_key}",
        on_change=on_image_change,
        args=("upload",),
    )
with tab_camera:
    captured = st.camera_input(
        "카메라로 촬영하기",
        key=f"camera_{st.session_state.input_key}",
        on_change=on_image_change,
        args=("camera",),
    )

# 둘 다 있으면 가장 최근에 올리거나 촬영한 쪽을 사용
if st.session_state.active_source == "camera":
    image_file = captured or uploaded
else:
    image_file = uploaded or captured

def get_processed(file) -> tuple[str | None, str | None]:
    """(data_url, 오류 메시지)를 반환. 같은 파일은 이 세션 안에서만 재사용(다른 세션과 공유하지 않음)."""
    cached = st.session_state.get("processed")
    if cached and cached[0] == file.file_id:
        return cached[1], cached[2]
    try:
        data_url, error = preprocess_image(file), None
    except ValueError as e:
        data_url, error = None, str(e)
    st.session_state.processed = (file.file_id, data_url, error)
    return data_url, error


data_url = None
if image_file is not None:
    # 미리보기 전에 검증: 확장자만 맞고 손상된 파일이면 이미지 표시가 실패함
    data_url, error = get_processed(image_file)
    if error:
        st.error(error)
    else:
        st.markdown(ui.preview_html(data_url), unsafe_allow_html=True)
else:
    st.session_state.pop("processed", None)  # 사진을 지우면 처리 결과도 메모리에서 제거

limit_reached = st.session_state.analysis_count >= MAX_ANALYSES_PER_SESSION
if limit_reached:
    st.warning(f"이번 세션의 분석 횟수({MAX_ANALYSES_PER_SESSION}회)를 모두 사용했어요. 이용해 주셔서 감사합니다!")

if st.button(
    "🔍 관상 보기",
    key="analyze",
    type="primary",
    disabled=data_url is None or limit_reached,
    use_container_width=True,
):
    with st.spinner("🔮 관상가가 얼굴을 살펴보는 중입니다..."):
        try:
            raw = analyze_face(data_url, style)
        except AnalysisError as e:
            # 실패한 시도는 횟수에서 차감하지 않음
            st.session_state.result = {"error": str(e)}
        else:
            st.session_state.analysis_count += 1
            if is_no_face(raw):
                st.session_state.result = {"no_face": True}
            else:
                body, scores = split_scores(raw)
                st.session_state.result = {"body": body, "scores": scores, "style": style}
    st.rerun()  # 사이드바 남은 횟수 등 갱신


def render_result(result: dict) -> None:
    sections, leftovers = ui.split_sections(result["body"])

    def card(key: str, fallback_title: str):
        heading, content = sections[key]
        with st.container(key=f"card-{key}"):
            st.markdown(ui.card_title(heading or fallback_title), unsafe_allow_html=True)
            st.markdown(content)

    if "first" in sections:
        card("first", "✨ 첫인상")

    if "parts" in sections:
        heading, content = sections["parts"]
        intro, parts = ui.split_parts(content)
        with st.container(key="card-parts"):
            st.markdown(ui.card_title(heading), unsafe_allow_html=True)
            if intro:
                st.markdown(intro)
            for i, (title, text) in enumerate(parts):
                with st.expander(title, expanded=i == 0):
                    st.markdown(text)

    if result["scores"]:
        with st.container(key="card-scores"):
            st.markdown(ui.card_title("📊 운세 별점"), unsafe_allow_html=True)
            st.markdown(ui.scores_html(result["scores"]), unsafe_allow_html=True)

    for key, fallback in (("fortune", "🔮 종합 운세"), ("animal", "🐾 닮은 동물상"), ("advice", "🍀 개운 조언")):
        if key in sections:
            card(key, fallback)

    # 모델이 형식을 따르지 않은 경우에도 내용이 사라지지 않도록 나머지를 그대로 표시
    if leftovers:
        with st.container(key="card-etc"):
            st.markdown(leftovers)


def download_text(result: dict) -> str:
    text = f"# 🔮 AI 관상가 결과 ({result['style']})\n\n{result['body']}\n"
    if result["scores"]:
        lines = [f"- {ui.SCORE_ICONS[k]}: {'★' * v}{'☆' * (5 - v)} ({v}/5)" for k, v in result["scores"].items()]
        text += "\n## 📊 운세 별점\n" + "\n".join(lines) + "\n"
    text += "\n> 본 결과는 재미를 위한 것이며 과학적 근거가 없습니다.\n"
    return text


# ---- 결과 ----
result = st.session_state.result
if result:
    st.divider()
    if result.get("error"):
        st.error(result["error"])
    elif result.get("no_face"):
        st.warning("😅 얼굴을 찾지 못했어요. 얼굴이 잘 보이는 사진을 올려주세요.")
    else:
        render_result(result)
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "💾 결과 다운로드",
                data=download_text(result),
                file_name="관상_결과.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col2:
            st.button("🔄 다른 사진으로 다시 보기", on_click=reset, use_container_width=True)

st.markdown(
    '<div class="footer-note">본 서비스의 결과는 재미를 위한 것이며 어떠한 과학적·의학적 근거도 없습니다.</div>',
    unsafe_allow_html=True,
)
