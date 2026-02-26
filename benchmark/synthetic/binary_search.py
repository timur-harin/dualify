# Treat values as sorted arr = [a0, a1, a2, a3].
# Return index of target if found, else return -1.
def binary_search(a0: int, a1: int, a2: int, a3: int, target: int) -> int:
    arr = [a0, a1, a2, a3]
    left = 0
    right = len(arr) - 1

    while left <= right:
        mid = left + (right - left) // 2
        if arr[mid] == target:
            return mid
        if arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1

    return -1

