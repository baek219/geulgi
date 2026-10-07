"""
긁기전에 - 자료 수집 프로그램

동행복권 홈페이지에 공개된 정보를 읽어서 data.json 파일을 새로 만듭니다.
 - 스피또: 판매 중인 회차의 출고율, 등수별 남은 매수, 회차별 1등 판매점, 1등 많이 나온 판매점
 - 로또: 최신 당첨번호, 등수별 당첨금, 1등 판매점, 번호별 나온 횟수(통계)

사용법:  python collect.py
(추가 설치 필요 없음 - 파이썬 기본 기능만 사용)

중간에 하나라도 실패하면 기존 data.json은 그대로 두고 멈춥니다.
"""

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://www.dhlottery.co.kr"
DATA_FILE = "data.json"
KST = timezone(timedelta(hours=9))
SPEETTO_CODES = {"SP2000": "LP35", "SP1000": "LP34", "SP500": "LP33"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE + "/",
}


def get_json(path):
    """동행복권에서 자료 하나를 읽어옵니다. 세 번까지 다시 시도합니다."""
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(BASE + path, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as res:
                body = res.read().decode("utf-8")
            time.sleep(0.25)  # 동행복권 서버에 부담을 주지 않도록 잠깐 쉬기
            return json.loads(body)
        except Exception as e:  # noqa: BLE001
            last_error = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"자료를 못 가져왔어요: {path} ({last_error})")


def lotto_row(r):
    return {
        "ep": r["ltEpsd"],
        "date": r["ltRflYmd"],
        "nums": [r[f"tm{i}WnNo"] for i in range(1, 7)],
        "bonus": r["bnsWnNo"],
        "ranks": [{"n": r[f"rnk{k}WnNope"], "amt": r[f"rnk{k}WnAmt"]} for k in range(1, 6)],
    }


def get_lotto_round(ep):
    rows = get_json(f"/lt645/selectPstLt645InfoNew.do?srchDir=center&srchLtEpsd={ep}")["data"]["list"]
    for r in rows:
        if r["ltEpsd"] == ep:
            return r
    raise RuntimeError(f"로또 {ep}회 자료가 없어요")


def unique_shops(shops):
    seen, out = set(), []
    for s in shops:
        key = (s.get("shpNm"), s.get("shpAddr"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"n": (s.get("shpNm") or "").strip(), "a": " ".join((s.get("shpAddr") or "").split())})
    return out


def speetto_first_shops(code, ep):
    data = get_json(
        f"/wnprchsplcsrch/selectStWnShp.do?srchWnShpRnk=all&srchLtEpsd={ep}&srchShpLctn=&srchLtGdsCd={code}"
    )["data"]
    shops = (data or {}).get("list") or []
    return [s for s in shops if s.get("wnShpRnk") == 1 or s.get("wnRnkVl") == 1]


def main():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            old = json.load(f)
    except FileNotFoundError:
        old = {}

    main_info = get_json("/selectMainInfo.do")["data"]["result"]

    # ---------- 스피또: 판매 중인 회차 ----------
    speetto = []
    for s in main_info["sellList"]["st"]:
        speetto.append({
            "type": s["stGmTypeCd"], "ep": s["stEpsd"], "rate": s["stSpmtRt"],
            "r1": s["stRnk1Rt"], "r2": s["stRnk2Rt"], "r3": s["stRnk3Rt"],
            "prize1": s["rnk1Atm"], "asOf": s["dataChgDt"],
            "saleEnd": s["stNtslEndDt"], "payEnd": s["stGiveEndDt"], "status": s["ntslStatus"],
        })
    if not speetto:
        raise RuntimeError("스피또 판매 정보가 비어 있어요")

    # ---------- 스피또: 1등 판매점 (회차별 + 많이 나온 곳 순위) ----------
    winners, top = {}, {}
    current = {(s["type"], s["ep"]) for s in speetto}
    for t, code in SPEETTO_CODES.items():
        eps = [x["ltEpsd"] for x in get_json(f"/wnprchsplcsrch/selectStEpsdInfo.do?srchLtGdsCd={code}")["data"]["list"]]
        tally = {}
        for ep in eps:
            ones = speetto_first_shops(code, ep)
            if (t, ep) in current:
                winners[f"{t}_{ep}"] = unique_shops(ones)
            counted = set()  # 세트 당첨(같은 곳에서 2장)은 1번으로 셉니다
            for s in ones:
                k = s.get("ltShpId") or s.get("shpNm")
                if k in counted:
                    continue
                counted.add(k)
                if k not in tally:
                    tally[k] = {"n": (s.get("shpNm") or "").strip(),
                                "a": " ".join((s.get("shpAddr") or "").split()), "c": 0}
                tally[k]["c"] += 1
        top[t] = {"rounds": len(eps), "top": sorted(tally.values(), key=lambda x: -x["c"])[:6]}
    for t, ep in current:
        winners.setdefault(f"{t}_{ep}", [])

    # ---------- 로또: 최신 회차 ----------
    recent = main_info["pstLtEpstInfo"]["lt645"]
    latest_ep = max(r["ltEpsd"] for r in recent)
    latest = lotto_row(next(r for r in recent if r["ltEpsd"] == latest_ep))

    first_shops = [
        {"n": s["shpNm"].strip(), "a": " ".join(s["shpAddr"].split()), "how": s.get("atmtPsvYnTxt", "")}
        for s in get_json(
            f"/wnprchsplcsrch/selectLtWnShp.do?srchWnShpRnk=1&srchLtEpsd={latest_ep}&srchShpLctn="
        )["data"]["list"]
    ]

    # ---------- 로또: 번호별 나온 횟수 (지난번 이후 새 회차만 더하기) ----------
    stats = (old.get("lotto") or {}).get("stats") or {"lastRound": 0, "counts": [0] * 45}
    counts = list(stats["counts"])
    for ep in range(stats["lastRound"] + 1, latest_ep + 1):
        r = get_lotto_round(ep)
        for i in range(1, 7):
            counts[r[f"tm{i}WnNo"] - 1] += 1
    stats = {"lastRound": latest_ep, "counts": counts}

    new = {
        "updatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "source": "동행복권 공개 정보",
        "speetto": speetto,
        "speettoWinners": winners,
        "speettoTop": top,
        "lotto": {"latest": latest, "firstShops": first_shops, "stats": stats},
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    print(f"완료: 스피또 {len(speetto)}개 회차, 로또 {latest_ep}회까지 저장했어요")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("실패:", e)
        sys.exit(1)
