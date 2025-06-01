from pathlib import Path
import json
import numpy as np
from statistics import mean, pstdev  # pstdev: 모집단 표준편차
import sqlite3
import matplotlib.pyplot as plt
from math import erf, sqrt

BASE_DIR: Path = Path(__file__).resolve().parents[1]
FILE_PATH: Path = BASE_DIR / "data" / "parsed" / "Cooler_parsed.json"


def check_cooler_noise():
    average = 0
    variance = 0
    noise_values = []

    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 각 아이템의 max_noise 처리
    for item in data:
        spec = item.get('spec', {})
        max_noise = spec.get('max_noise')

        # 리스트인지 단일값인지 확인
        values = max_noise if isinstance(max_noise, list) else [max_noise]

        for v in values:
            if v is None:
                continue
            # 숫자 부분만 남기고 파싱 (예: "31.6dBA" → 31.6)
            num = float(''.join(ch for ch in v if (ch.isdigit() or ch == '.')))
            noise_values.append(num)

    print(noise_values)
    print(len(noise_values))
    avg_noise = mean(noise_values)
    std_noise = pstdev(noise_values)
    max_noise = max(noise_values)
    min_noise = min(noise_values)

    print(f"noise 평균: {avg_noise:.2f} dBA")
    print(f"noise 표준편차: {std_noise:.2f} dBA")
    print(f"noise 최솟값: {max_noise:.2f} dBA")
    print(f"noise 최대값: {min_noise:.2f} dBA")

    conn = sqlite3.connect('../askspec.db')
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO score_statistics(name, category, value)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            category   = excluded.category,
            value  = excluded.value,
            updated_at = CURRENT_TIMESTAMP
    """, ("noise_average", "Cooler", avg_noise))

    cursor.execute("""
        INSERT INTO score_statistics(name, category, value)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            category   = excluded.category,
            value  = excluded.value,
            updated_at = CURRENT_TIMESTAMP
    """, ("noise_standard_deviation", "Cooler", std_noise))

    conn.commit()
    conn.close()

    return noise_values, avg_noise, std_noise


def plot_nose_distribution(noise_values, bins = 20):
    noise_array = np.array(noise_values, dtype=float)

    # 히스토그램 그리기
    plt.figure()
    plt.hist(noise_array, bins=bins)
    plt.title('Noise Distribution')
    plt.xlabel('dBA')
    plt.ylabel('Frequency')
    plt.tight_layout()
    plt.show()

def plot_noise_score_distribution(noise_values, noise_average, noise_std, bins=20):
    """
    noise_values: list or array of noise measurements (floats)
    noise_average: 평균 소음값 (float)
    noise_std: 소음 표준편차 (float)
    bins: 히스토그램 막대 수 (int)

    이 함수는 noise_score를 계산하여 분포를 히스토그램으로 그리고,
    각 쿨러별 noise_score 배열을 반환합니다.
    """
    noise_array = np.array(noise_values, dtype=float)
    z = (noise_array - noise_average) / noise_std
    z_min, z_max = z.min(), z.max()
    # 범위가 0이 되지 않도록 안전 처리
    if z_max == z_min:
        noise_score = np.full_like(z, 50.0)
    else:
        noise_score = (z - z_min) / (z_max - z_min) * 100
        noise_score = np.clip(noise_score, 0, 100)

    # noise_score 평균 출력
    print(f"Noise Score 평균: {noise_score.mean():.2f}")
    # 히스토그램 그리기
    plt.figure()
    plt.hist(noise_score, bins=bins)
    plt.title('Noise Score Distribution')
    plt.xlabel('Noise Score')
    plt.ylabel('Frequency')
    plt.tight_layout()
    plt.show()

def plot_noise_minmax_score_distribution(noise_values, bins=20):
    """
    noise_values: list of noise measurements (floats)
    bins: 히스토그램 막대 수 (int)

    - 소음은 '작을수록 좋다'고 가정하고,
      score = (max_noise - noise) / (max_noise - min_noise) * 100
      으로 0~100 구간의 점수를 계산합니다.
    - noise = min_noise 일 때 100점, noise = max_noise 일 때 0점입니다.
    """
    arr = np.array(noise_values, dtype=float)
    min_n, max_n = arr.min(), arr.max()

    # 범위가 0일 때 예외 처리
    if max_n == min_n:
        scores = np.full_like(arr, 50.0)
    else:
        # 0~100 스케일로 변환
        scores = (max_n - arr) / (max_n - min_n) * 100
        scores = np.clip(scores, 0, 100)

    # 히스토그램
    plt.figure()
    plt.hist(scores, bins=bins)
    plt.title('Min Max score')
    plt.xlabel('Noise Score')
    plt.ylabel('Frequency')
    plt.tight_layout()
    plt.show()

    return scores

if __name__ == "__main__":
    noise, noise_average, noise_standard_deviation= check_cooler_noise()
    plot_nose_distribution(noise)
    plot_noise_score_distribution(noise, noise_average, noise_standard_deviation)
    plot_noise_minmax_score_distribution(noise, bins=20)