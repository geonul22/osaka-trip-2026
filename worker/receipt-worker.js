// 영수증 읽기용 Cloudflare Worker
// 비밀값(Secret) 이름: ANTHROPIC_API_KEY  (Cloudflare 설정 화면에서만 넣고, 이 파일에는 절대 적지 않아요)
const ALLOWED_ORIGIN = 'https://geonul22.github.io';
const MODEL = 'claude-haiku-5-5';
const MAX_IMAGE_CHARS = 1_800_000; // 사진이 너무 크면 거절 (비용 보호)

const cors = {
  'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};
const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { ...cors, 'Content-Type': 'application/json' } });

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') return new Response(null, { headers: cors });
    if (request.method !== 'POST') return json({ error: 'POST만 가능해요' }, 405);
    if (request.headers.get('Origin') !== ALLOWED_ORIGIN) return json({ error: '허용되지 않은 주소예요' }, 403);

    let body;
    try { body = await request.json(); } catch { return json({ error: '잘못된 요청이에요' }, 400); }
    const image = body && body.image; // base64 (JPEG)
    if (!image || typeof image !== 'string' || image.length > MAX_IMAGE_CHARS) {
      return json({ error: '사진이 없거나 너무 커요' }, 400);
    }

    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 200,
        messages: [{
          role: 'user',
          content: [
            { type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: image } },
            { type: 'text', text:
              '이 일본 영수증을 읽고 JSON만 답하세요. 다른 말은 쓰지 마세요.\n' +
              '{"store":"가게 이름(한국어로, 모르면 원문)","total":세금 포함 최종 결제 금액(엔, 숫자만),"date":"YYYY-MM-DD 또는 빈 문자열"}\n' +
              '영수증이 아니거나 금액을 못 읽으면 {"store":"","total":0,"date":""}' },
          ],
        }],
      }),
    });
    if (!res.ok) return json({ error: '읽기에 실패했어요 (' + res.status + ')' }, 502);

    const data = await res.json();
    const text = (data.content || []).map(c => c.text || '').join('');
    const m = text.match(/\{[\s\S]*\}/);
    let out = { store: '', total: 0, date: '' };
    try { if (m) out = { ...out, ...JSON.parse(m[0]) }; } catch {}
    out.total = Math.round(Number(out.total)) || 0;
    return json(out);
  },
};
