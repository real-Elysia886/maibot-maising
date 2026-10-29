const { cloudsearch, song_url_v1, lyric } = require('NeteaseCloudMusicApi');

const fs = require('fs');
const path = require('path');
const credentialFile = path.join(__dirname, '.music_u');
const MUSIC_U = process.env.NETEASE_MUSIC_U ||
    (fs.existsSync(credentialFile) ? fs.readFileSync(credentialFile, 'utf8').trim() : '');

function parseTime(timeStr) {
    const m = timeStr.match(/(\d+):(\d+(?:\.\d+)?)/);
    if (m) {
        return parseInt(m[1]) * 60 + parseFloat(m[2]);
    }
    return 0.0;
}

const metaKeywords = [
    '作词', '作曲', '编曲', '制作', '合声', '和声', '吉他', '贝斯', '鼓',
    '录音', '混音', '母带', '监制', '出品', '发行', '原唱', '弦乐', '企划',
    '统筹', '词：', '曲：', '唱：', '演唱：', 'OP:', 'SP:', 'Studio',
    'Lyricist', 'Composer', 'Arranger', 'Producer', 'Vocals', 'Music', 'Mastering', 'Mixing', 'Recording'
];

async function findVipSong(keyword, targetDuration = 10.0) {
    const cookie = `MUSIC_U=${MUSIC_U}; os=pc; appver=2.9.7;`;

    // 优先按用户完整输入搜索；没有结果时再尝试第一个词。
    const searchKeyword = keyword.trim();
    const tokens = searchKeyword.split(/[\s,，。！!？\?]+/);

    // Search songs
    let sRes = await cloudsearch({ keywords: searchKeyword, type: 1, limit: 25, cookie });
    let songs = (sRes.body.result && sRes.body.result.songs) || [];
    if (!songs.length && tokens.length > 1 && tokens[0].length >= 2) {
        sRes = await cloudsearch({ keywords: tokens[0], type: 1, limit: 25, cookie });
        songs = (sRes.body.result && sRes.body.result.songs) || [];
    }
    if (!songs.length) {
        throw new Error(`未找到包含 "${keyword}" 的歌曲`);
    }

    const badWords = [
        'DJ', 'dj', 'Remix', 'remix', '慢摇', '电音', '车载', '铃声',
        '片段', '伴奏', '纯音乐', '八音盒', '钢琴版', '自制',
        '变速', '加快', '减速', '文案', '语录', '独白', '旁白', '电台', '评论区', '伤感语录', '口白'
    ];
    let candidateSongs = songs.filter(s => !badWords.some(bw => s.name.includes(bw)));
    if (!candidateSongs.length) candidateSongs = songs;

    const cleanKeyword = keyword.replace(/[，。？！\.,!\s]/g, '');

    const normalize = text => String(text || '').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
    const normalizedQuery = normalize(keyword);
    const queryParts = tokens.map(normalize).filter(part => part.length >= 2);

    // 完整歌名匹配优先，再按歌手和版本排序。
    candidateSongs.sort((a, b) => {
        const titleRank = song => {
            const title = normalize(song.name);
            if (title && title === normalizedQuery) return 2;
            if (title.length >= 2 && normalizedQuery.includes(title)) return 1;
            return 0;
        };
        const titleDifference = titleRank(b) - titleRank(a);
        if (titleDifference) return titleDifference;

        // 歌手匹配优先
        const aArtists = (a.ar || []).map(x => x.name).join(' ');
        const bArtists = (b.ar || []).map(x => x.name).join(' ');
        const aArtistHit = (cleanKeyword.includes('周杰伦') && (aArtists.includes('周杰伦') || aArtists.includes('Jay'))) ||
                           (a.ar || []).some(x => cleanKeyword.includes(x.name));
        const bArtistHit = (cleanKeyword.includes('周杰伦') && (bArtists.includes('周杰伦') || bArtists.includes('Jay'))) ||
                           (b.ar || []).some(x => cleanKeyword.includes(x.name));
        if (aArtistHit !== bArtistHit) return bArtistHit ? 1 : -1;

        // 2. 版本降权
        const aHasVersion = /[\(（].*?(?:版|翻唱|伴奏|重温|混音|改编|片段)[\)）]/.test(a.name) || /深情版|女声版|男生版|热搜版/.test(a.name);
        const bHasVersion = /[\(（].*?(?:版|翻唱|伴奏|重温|混音|改编|片段)[\)）]/.test(b.name) || /深情版|女声版|男生版|热搜版/.test(b.name);
        if (aHasVersion !== bHasVersion) return aHasVersion ? 1 : -1;

        // 3. 歌名匹配度
        const aClean = a.name.replace(/[\(\)（）\s]/g, '');
        const bClean = b.name.replace(/[\(\)（）\s]/g, '');
        const aExact = a.name === keyword ? 3 : (aClean === cleanKeyword ? 2 : (aClean.startsWith(cleanKeyword) ? 1 : 0));
        const bExact = b.name === keyword ? 3 : (bClean === cleanKeyword ? 2 : (bClean.startsWith(cleanKeyword) ? 1 : 0));
        if (aExact !== bExact) return bExact - aExact;
        return 0;
    });

    for (const song of candidateSongs) {
        let lRes = null;
        try {
            lRes = await lyric({ id: song.id, cookie });
        } catch (e) {
            continue;
        }
        const lrcText = (lRes.body.lrc && lRes.body.lrc.lyric) || '';
        if (!lrcText) continue;

        // 搜索服务可能返回无关歌曲，例如把歌名误识别为歌手名。
        // 要求歌名或歌词与用户的输入有明确关联，避免静默替换曲目。
        const title = normalize(song.name);
        const titleMatches = title.length >= 2 && (
            normalizedQuery.includes(title) || queryParts.some(part => title.includes(part))
        );
        const lyricMatches = lrcText.split('\n').some(line => {
            const text = normalize(line.replace(/\[[^\]]*\]/g, ''));
            return text.length >= 2 && queryParts.some(part =>
                text.includes(part) || (text.length >= 4 && part.includes(text))
            );
        });
        if (!titleMatches && !lyricMatches) continue;

        let trackData = null;
        // 按账号和歌曲实际可用的音质降级，不绕过版权或会员限制。
        for (const level of ['lossless', 'exhigh', 'higher', 'standard']) {
            try {
                const result = await song_url_v1({ id: song.id, level, cookie });
                const track = result.body.data && result.body.data[0];
                if (track && track.url && !track.freeTrialInfo) {
                    trackData = track;
                    break;
                }
            } catch (e) {
                // 某个音质不可用时继续尝试其他等级。
            }
        }
        if (!trackData) continue;

        const rawLines = [];
        for (const line of lrcText.split('\n')) {
            const matches = line.match(/\[(\d+:\d+(?:\.\d+)?)\](.*)/);
            if (matches) {
                const t = parseTime(matches[1]);
                const txt = matches[2].trim();
                if (txt) rawLines.push({ time: t, text: txt });
            }
        }
        rawLines.sort((a, b) => a.time - b.time);

        // 过滤演职员信息与前 12 秒标题，过滤纯表情符号
        const cleanSongName = song.name.replace(/[，。？！\.,!\s\(\)（）]/g, '');
        const validLines = rawLines.filter(item => {
            if (metaKeywords.some(mk => item.text.includes(mk))) return false;
            if (item.time < 12.0 && (item.text.includes(cleanSongName) || item.text.includes('-') || item.text.includes(':') || item.text.includes('：'))) {
                return false;
            }
            // 必须至少包含 2 个有效汉字或英文单词字母，杜绝颜文字与纯标点
            const letters = item.text.match(/[\u4e00-\u9fa5a-zA-Z]/g) || [];
            if (letters.length < 2) return false;
            return true;
        });

        if (!validLines.length) continue;

        // 匹配打分机制：寻找最高相似度乐句，同时优先避开说唱段落
        let bestIdx = -1;
        let bestScore = -1;

        for (let i = 0; i < validLines.length; i++) {
            const line = validLines[i];
            const cleanTxt = line.text.replace(/[，。？！\.,!\s]/g, '');

            // 计算匹配重合度
            let matchLen = 0;
            if (cleanTxt === cleanKeyword) {
                matchLen = 100;
            } else if (cleanKeyword.includes(cleanTxt)) {
                matchLen = cleanTxt.length * 10;
            } else if (cleanTxt.includes(cleanKeyword)) {
                matchLen = cleanKeyword.length * 10;
            } else {
                // 子串重合
                for (let len = 4; len <= cleanKeyword.length; len++) {
                    for (let s = 0; s <= cleanKeyword.length - len; s++) {
                        const sub = cleanKeyword.substring(s, s + len);
                        if (cleanTxt.includes(sub)) {
                            matchLen = Math.max(matchLen, len * 5);
                        }
                    }
                }
            }

            if (matchLen > 0) {
                // 乐句时长与语速评估（识别真正拉长音的副歌，避开快嘴说唱）
                const dur = (i + 1 < validLines.length) ? (validLines[i + 1].time - line.time) : 5.0;
                const charSpeed = cleanTxt.length / Math.max(dur, 0.5); // 字数/秒

                let score = matchLen;
                // 真正的抒情慢歌副歌，字速慢（<= 2.5字/秒），拉长音多，大幅加分！
                if (charSpeed <= 2.2 && dur >= 3.0) {
                    score += 50;
                } else if (charSpeed > 3.5) {
                    // 说唱段落（字速极快，一秒四五个字），扣分
                    score -= 30;
                }

                // 副歌黄金时段加分（45秒 ~ 180秒）
                if (line.time >= 40.0 && line.time <= 200.0) {
                    score += 20;
                }

                if (score > bestScore) {
                    bestScore = score;
                    bestIdx = i;
                }
            }
        }

        // 如果用户仅搜索歌名且未显式命中歌词：
        if (bestIdx === -1) {
            // 策略：寻找副歌（40s 之后、语速适中、最长或最抒情的句子）
            let chorusIdx = -1;
            let chorusScore = -1;
            for (let i = 0; i < validLines.length; i++) {
                const line = validLines[i];
                if (line.time < 25.0) continue;
                const dur = (i + 1 < validLines.length) ? (validLines[i + 1].time - line.time) : 5.0;
                const cleanTxt = line.text.replace(/[，。？！\.,!\s]/g, '');
                const charSpeed = cleanTxt.length / Math.max(dur, 0.5);

                let sc = 0;
                if (cleanTxt.includes(cleanSongName)) sc += 80;
                if (charSpeed <= 2.2 && dur >= 3.5) sc += 50; // 慢速抒情长音加分
                if (charSpeed > 3.5) sc -= 50; // 避开说唱
                if (line.time >= 45.0 && line.time <= 180.0) sc += 30;

                if (sc > chorusScore) {
                    chorusScore = sc;
                    chorusIdx = i;
                }
            }
            bestIdx = (chorusIdx !== -1) ? chorusIdx : 0;
        }

        const target = validLines[bestIdx];
        let tStart = target.time;

        // 乐句拼接与时长控制（智能拼接 2~3 句，支持 8~14 秒完整大副歌）
        let nextIdx = bestIdx + 1;
        let tEnd = (nextIdx < validLines.length) ? validLines[nextIdx].time : tStart + 6.0;
        let lyricText = target.text;

        const maxDur = Math.max(7.5, Math.min(parseFloat(targetDuration) || 11.0, 16.0));
        while (tEnd - tStart < maxDur - 2.5 && nextIdx < validLines.length) {
            lyricText += " " + validLines[nextIdx].text;
            nextIdx++;
            tEnd = (nextIdx < validLines.length) ? validLines[nextIdx].time : tStart + maxDur;
        }

        if (tEnd - tStart > maxDur + 1.5) {
            tEnd = tStart + maxDur;
        } else if (tEnd - tStart < 4.5) {
            tEnd = tStart + 5.5;
        }

        tStart = Math.max(0.0, tStart - 0.2);
        tEnd += 0.3;

        return {
            song_id: song.id,
            song_name: song.name,
            artist: song.ar[0] ? song.ar[0].name : '未知歌手',
            media_url: trackData.url,
            format: trackData.type || 'unknown',
            bitrate: trackData.br || 0,
            matched_lyric: lyricText,
            start_time: tStart,
            end_time: tEnd,
            duration: tEnd - tStart
        };
    }

    throw new Error(`未找到“${keyword}”可用的完整音频和歌词；可能受版权、地区、账号权益或登录状态限制`);
}

async function main() {
    const kw = process.argv[2] || "听妈妈的话";
    const dur = process.argv[3] ? parseFloat(process.argv[3]) : 11.0;
    try {
        const res = await findVipSong(kw, dur);
        console.log(JSON.stringify(res));
    } catch (e) {
        console.error(JSON.stringify({ error: e.message }));
        process.exit(1);
    }
}

main();
