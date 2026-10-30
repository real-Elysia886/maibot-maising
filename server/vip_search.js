const { cloudsearch, song_url_v1, lyric, song_chorus } = require('NeteaseCloudMusicApi');
const fs = require('fs');
const path = require('path');
const credentialFile = path.join(__dirname, '.music_u');
const MUSIC_U = process.env.NETEASE_MUSIC_U ||
    (fs.existsSync(credentialFile) ? fs.readFileSync(credentialFile, 'utf8').trim() : '');
const normalize = text => String(text || '').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
const normalizeArtist = text => String(text || '').normalize('NFKC').toLowerCase().replace(/\s/g, '');
const cleanTitle = text => normalize(String(text || '').replace(/[（(][^）)]*(?:cover|翻唱|live|现场|版|伴奏|remix|改编|慢放|\d+(?:\.\d+)?x)[^）)]*[）)]/ig, ''));
const isCover = song => /cover|翻唱|翻自/i.test(song.name || '') || /cover|翻唱|翻自/i.test((song.alia || []).join(' '));
const isVariant = song => /[（(][^）)]*(?:cover|翻唱|live|现场|版|伴奏|remix|改编)[^）)]*[）)]/i.test(song.name || '');
const excluded = /伴奏|纯音乐|八音盒|铃声|语录|独白|旁白|电台|remix|dj|慢摇|车载|慢放|变速|加快|减速|[（(][^）)]*\d+(?:\.\d+)?x[^）)]*[）)]/i;
const metadata = /^(作词|作曲|编曲|制作人|制作|合声|和声|吉他|贝斯|鼓|录音|混音|母带|监制|出品|发行|原唱|弦乐|企划|统筹|演唱|词|曲|唱|op|sp|lyricist|composer|arranger|producer|vocals|mastering|recording)\s*[:：]/i;
const apiTimeout = 5000;
let searchDeadline = 0;
function timed(request) {
    let timer;
    const remaining = searchDeadline ? searchDeadline - Date.now() : apiTimeout;
    if (remaining <= 0) return Promise.reject(new Error('搜索服务超时'));
    return Promise.race([Promise.resolve().then(request), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('搜索服务超时')), Math.min(apiTimeout, remaining));
    })]).finally(() => clearTimeout(timer));
}
function parseLyrics(lrc) {
    const lines = [];
    for (const raw of String(lrc || '').split(/\r?\n/)) {
        const stamps = [...raw.matchAll(/\[(\d+):(\d+(?:\.\d+)?)\]/g)];
        const text = raw.replace(/\[[^\]]*\]/g, '').trim();
        if (!text || metadata.test(text) || normalize(text).length < 2) continue;
        for (const stamp of stamps) lines.push({time: Number(stamp[1]) * 60 + Number(stamp[2]), text});
    }
    return lines.sort((a, b) => a.time - b.time).filter((line, i, arr) =>
        !i || line.time !== arr[i - 1].time || line.text !== arr[i - 1].text);
}
// Longest common contiguous fragment: repeated words must match in order.
function longestMatch(a, b) {
    a = normalize(a).slice(0, 160); b = normalize(b).slice(0, 320);
    let prev = new Uint16Array(b.length + 1), best = 0, end = 0;
    for (let i = 1; i <= a.length; i++) {
        const row = new Uint16Array(b.length + 1);
        for (let j = 1; j <= b.length; j++) {
            if (a[i - 1] === b[j - 1]) {
                row[j] = prev[j - 1] + 1;
                if (row[j] > best) { best = row[j]; end = j; }
            }
        }
        prev = row;
    }
    return {length: best, start: end - best, end};
}
function longestOverlap(a, b) { return longestMatch(a, b).length; }
function matchLyrics(query, lines) {
    const q = normalize(query).slice(0, 160);
    if (q.length < 4) return {score: 0, index: -1};
    let best = {score: 0, index: -1};
    for (let i = 0; i < lines.length; i++) {
        const window = lines.slice(i, i + 3).map(x => normalize(x.text));
        const match = longestMatch(q, window.join(''));
        const score = match.length / q.length;
        if (score > best.score) {
            let before = 0, startLine = 0, endLine = 0;
            for (let j = 0; j < window.length; j++) {
                if (before <= match.start) startLine = j;
                if (before < match.end) endLine = j;
                before += window[j].length;
            }
            best = {score, index: i + startLine, endIndex: i + endLine};
        }
    }
    return best;
}
function sameComposition(a, b) {
    const aa = normalize(a.lines.map(line => line.text).join('')).slice(0, 160);
    const bb = normalize(b.lines.map(line => line.text).join('')).slice(0, 320);
    return aa.length >= 12 && longestOverlap(aa, bb) / Math.min(aa.length, 80) >= 0.6;
}
function titleEvidence(query, song) {
    const q = normalize(query), title = cleanTitle(song.name);
    if (!title || title.length < 2) return null;
    const artists = (song.ar || song.artists || []).map(a => normalizeArtist(a.name)).filter(Boolean);
    if (q === title) return {rank: 3, lyric: '', artistMatch: false};
    for (const artist of artists) {
        if (q === title + artist || q === artist + title) return {rank: 4, lyric: '', artistMatch: true};
    }
    // Only treat a title as explicit when separated in the original input.
    const parts = String(query).split(/[\s,，。！!？?]+/).filter(Boolean);
    const index = parts.findIndex(part => normalize(part) === title);
    if (index >= 0 && parts.length > 1) {
        const rest = parts.filter((_, i) => i !== index);
        const artistMatch = rest.some(x => artists.includes(normalizeArtist(x)));
        const remaining = rest.filter(x => !artists.includes(normalizeArtist(x))).join(' ');
        return {rank: artistMatch ? 4 : 2, lyric: remaining, artistMatch};
    }
    return null;
}
function chooseSection(lines, lyricMatch, songDuration, requestedDuration, chorusStart = null) {
    const length = Math.max(6, Math.min(Number(requestedDuration) || 11, 16));
    let index = lyricMatch.index;
    let source = index >= 0 ? 'lyric' : 'heuristic';
    if (index < 0 && Number.isFinite(chorusStart) && chorusStart > 0 &&
        (!songDuration || chorusStart < songDuration - 4)) {
        let nearest = -1, delta = Infinity;
        for (let i = 0; i < lines.length; i++) {
            const distance = Math.abs(lines[i].time - chorusStart);
            if (distance < delta) { nearest = i; delta = distance; }
        }
        // An unrelated or sparse timestamp must not displace the fallback.
        if (delta <= 10) { index = nearest; source = 'chorus'; }
    }
    if (index < 0) {
        const counts = new Map();
        for (const line of lines) { const text = normalize(line.text); counts.set(text, (counts.get(text) || 0) + 1); }
        let best = -Infinity; index = 0;
        for (let i = 0; i < lines.length; i++) {
            const remaining = songDuration ? songDuration - lines[i].time : Infinity;
            if (remaining < 4) continue;
            const future = lines.slice(i, i + 3);
            const repeat = future.reduce((n, l) => n + Math.min((counts.get(normalize(l.text)) || 1) - 1, 2), 0);
            const score = repeat * 3 + Math.min(future.length, 3) + (lines[i].time >= 25 ? 1 : 0) - (future.length === 1 ? 3 : 0);
            if (score > best) { best = score; index = i; }
        }
    }
    // For an explicitly requested final line retain it and include earlier context.
    if (lyricMatch.index >= 0 && songDuration && songDuration - lines[index].time < length / 2) {
        while (index > 0 && lines[lyricMatch.index].time - lines[index - 1].time <= length / 2) index--;
    }
    const start = Math.max(0, lines[index].time - 0.2);
    let end = start + length;
    if (lyricMatch.index >= 0 && lyricMatch.endIndex != null) {
        const next = lines[lyricMatch.endIndex + 1];
        if (next) end = Math.max(end, Math.min(start + 16, next.time));
    }
    if (songDuration && songDuration > start) end = Math.min(end, songDuration);
    const included = lines.filter(line => line.time >= lines[index].time && line.time < end);
    return {start_time: start, end_time: end, duration: end - start, section_source: source,
        matched_lyric: included.map(line => line.text).join(' ')};
}
async function findVipSong(keyword, targetDuration = 11) {
    searchDeadline = Date.now() + 35000;
    const query = String(keyword || '').trim();
    if (!query || normalize(query).length < 2) throw new Error('请输入歌名或至少两个有效字符的歌词');
    const cookie = `MUSIC_U=${MUSIC_U}; os=pc; appver=2.9.7;`;
    const jobs = [{keywords: query, type: 1, limit: 20, cookie}];
    if (normalize(query).length >= 4) {
        jobs.push({keywords: query.slice(0, 30), type: 1006, limit: 20, cookie});
        const parts = query.split(/[\s,，。！!？?]+/).filter(x => normalize(x).length >= 5);
        if (parts.length > 1) jobs.push({keywords: parts.slice(0, 2).join(' ').slice(0, 30), type: 1006, limit: 20, cookie});
    }
    const searches = await Promise.allSettled(jobs.map(job => timed(() => cloudsearch(job))));
    if (searches.every(x => x.status === 'rejected')) throw new Error('歌曲搜索服务暂时不可用或超时');
    const byId = new Map();
    const lists = searches.filter(x => x.status === 'fulfilled').map(x => x.value?.body?.result?.songs || []);
    for (let i = 0; i < 20; i++) {
        for (const list of lists) {
            const song = list[i];
            if (song && song.id && song.name && !byId.has(song.id)) byId.set(song.id, song);
        }
    }
    const songs = [...byId.values()].filter(s => !excluded.test(s.name)).slice(0, 20);
    if (!songs.length) throw new Error('没有找到匹配的歌曲，请补充歌名、歌手或歌词');
    const parts = query.split(/[\s,，。！!？?]+/).filter(Boolean);
    const looksLikeArtistRequest = parts.length === 2 && songs.some(song => {
        const title = cleanTitle(song.name);
        const artistNames = (song.ar || song.artists || []).map(a => normalize(a.name));
        return (normalize(parts[0]) === title && artistNames.includes(normalize(parts[1]))) ||
            (normalize(parts[1]) === title && artistNames.includes(normalize(parts[0])));
    });
    const assessed = [];
    // Bound simultaneous lyric requests and keep all evidence before choosing a song.
    for (let offset = 0; offset < songs.length; offset += 5) {
        const batch = await Promise.all(songs.slice(offset, offset + 5).map(async song => {
            try {
                const result = await timed(() => lyric({id: song.id, cookie}));
                const lines = parseLyrics(result?.body?.lrc?.lyric);
                if (!lines.length) return null;
                const title = titleEvidence(query, song);
                if (looksLikeArtistRequest && !(title && title.artistMatch)) return null;
                const lyricQuery = title ? title.lyric : query;
                const lm = matchLyrics(lyricQuery, lines);
                if (lyricQuery && (!lm.score || lm.score < 0.65)) return null;
                if (!title && lm.score < 0.65) return null;
                return {song, lines, title, lyricMatch: lm, score: title ? 10 + title.rank + lm.score : lm.score * 10};
            } catch (_) { return null; }
        }));
        assessed.push(...batch.filter(Boolean));
    }
    if (!assessed.length && Date.now() >= searchDeadline) throw new Error('搜索或歌词获取超时，请稍后重试');
    if (!assessed.length && looksLikeArtistRequest) throw new Error('未能确认指定歌手的歌曲或获取其歌词，请检查歌手名和版权情况');
    if (!assessed.length) throw new Error('未能确认匹配的歌曲或歌词，请补充歌名或歌手');
    // A phrase may also be used as the title of a short excerpt. When several
    // independently returned recordings of another title contain the full
    // phrase, use the lyric evidence rather than the excerpt's title alone.
    if (!looksLikeArtistRequest && parts.length > 1 && normalize(query).length >= 8) {
        for (const item of assessed) item.fullMatch = matchLyrics(query, item.lines);
        const counts = new Map();
        for (const item of assessed) {
            if (item.fullMatch.score >= 0.85) {
                const key = cleanTitle(item.song.name);
                counts.set(key, (counts.get(key) || 0) + 1);
            }
        }
        if ([...counts.values()].some(count => count >= 2)) {
            for (const item of assessed) {
                if (item.fullMatch.score >= 0.85) {
                    item.lyricMatch = item.fullMatch;
                    item.score = item.fullMatch.score * 10 + Math.min(counts.get(cleanTitle(item.song.name)) || 0, 4) * 0.15;
                } else {
                    item.score = -1;
                }
            }
        }
    }
    assessed.sort((a, b) => b.score - a.score || Number(isVariant(a.song)) - Number(isVariant(b.song)) || Number(isCover(a.song)) - Number(isCover(b.song)));
    const best = assessed[0];
    // Never fall back to a different song merely because an earlier source is unavailable.
    const targetTitle = cleanTitle(best.song.name);
    const candidates = assessed.filter(item => item.score >= 0 && cleanTitle(item.song.name) === targetTitle &&
        (item.song.id === best.song.id || sameComposition(best, item)));
    if ((!best.title || best.lyricMatch.index >= 0) && assessed.some(item => cleanTitle(item.song.name) !== targetTitle && Math.abs(item.score - best.score) < 0.5 && !sameComposition(best, item))) {
        throw new Error('歌词匹配到多首歌曲，请补充歌名或歌手');
    }
    const explicitArtist = Boolean(best.title && best.title.artistMatch);
    for (const item of candidates) {
        if (explicitArtist && !(item.title && item.title.artistMatch)) continue;
        let trackData = null;
        for (const level of ['lossless', 'exhigh', 'higher', 'standard']) {
            try {
                const result = await timed(() => song_url_v1({id: item.song.id, level, cookie}));
                const track = result?.body?.data?.[0];
                if (track && track.url && !track.freeTrialInfo) { trackData = track; break; }
            } catch (_) { /* Try the next available quality. */ }
        }
        if (!trackData) continue;
        const trackDuration = Number(trackData.time || item.song.dt || item.song.duration || 0) / 1000;
        let chorusStart = null;
        if (item.lyricMatch.index < 0 && typeof song_chorus === 'function') {
            try {
                const response = await timed(() => song_chorus({id: item.song.id, cookie}));
                const list = response?.body?.chorus || response?.body?.data;
                const entry = Array.isArray(list) ? list.find(x => String(x.id) === String(item.song.id)) : null;
                const start = Number(entry?.startTime) / 1000;
                const end = Number(entry?.endTime) / 1000;
                if (Number.isFinite(start) && Number.isFinite(end) && end > start) chorusStart = start;
            } catch (_) { /* Use the lyric heuristic when chorus data is unavailable. */ }
        }
        const section = chooseSection(item.lines, item.lyricMatch, trackDuration, targetDuration, chorusStart);
        if (section.duration < 2) continue;
        const artist = (item.song.ar || item.song.artists || [])[0]?.name || '未知歌手';
        const notice = isCover(item.song) ? `本次使用《${item.song.name}》的翻唱版本（${artist}）。` :
            isVariant(item.song) ? `本次使用《${item.song.name}》（${artist}）。` :
            item.song.id !== best.song.id ? `原先匹配的版本不可用，本次使用《${item.song.name}》（${artist}）。` :
            !explicitArtist && candidates.some(other => (other.song.ar || other.song.artists || [])[0]?.name !== artist)
                ? `本次选择《${item.song.name}》（${artist}），请注意演唱者。` : '';
        return {song_id: item.song.id, song_name: item.song.name, artist, media_url: trackData.url,
            format: trackData.type || 'unknown', bitrate: trackData.br || 0,
            ...section, match_type: item.lyricMatch.index >= 0 ? 'lyric' : 'title', selection_notice: notice};
    }
    if (Date.now() >= searchDeadline) throw new Error('搜索或音源获取超时，请稍后重试');
    throw new Error('已找到匹配歌曲，但当前账号没有可播放的完整音源');
}
async function main() {
    const kw = process.argv[2] || '听妈妈的话';
    const dur = process.argv[3] ? parseFloat(process.argv[3]) : 11;
    try { console.log(JSON.stringify(await findVipSong(kw, dur))); }
    catch (e) { console.error(e.message); process.exitCode = 1; }
}
if (require.main === module) main();
module.exports = {normalize, cleanTitle, parseLyrics, longestOverlap, matchLyrics, titleEvidence, chooseSection, findVipSong};
