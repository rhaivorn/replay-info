class RandomGenerator:
    MAGIC_NUMBERS = [
        0xf22d0e56,
        0x883126e9,
        0xc624dd2f,
        0x0702c49c,
        0x9e353f7d,
        0x6fdf3b64
    ]

    def __init__(self, seed_value):
        self.values = self._build_seed_array(seed_value)
    
    def _build_seed_array(self, seed):
        result = [0] * 6
        result[0] = (seed + self.MAGIC_NUMBERS[0]) & 0xFFFFFFFF
        
        for i in range(1, 6):
            result[i] = (result[i-1] + (self.MAGIC_NUMBERS[i] - self.MAGIC_NUMBERS[i-1])) & 0xFFFFFFFF
            
        return result

    def generate(self):
        s = self.values
        carry = 0

        # Cascade addition
        for i in range(4, -1, -1):
            s[i], carry = (s[i] + s[i + 1] + carry) & 0xFFFFFFFF, (s[i] + s[i + 1] + carry) >> 32

        # Handle overflow case
        if s[5] == 0xFFFFFFFF:
            s[5] = 0
            for i in range(4, -1, -1):
                if s[i] != 0xFFFFFFFF:
                    s[i] = (s[i] + 1) & 0xFFFFFFFF
                    break
                s[i] = 0
        else:
            s[5] = (s[5] + 1) & 0xFFFFFFFF

        return s[0]

    
    def get_value(self, minimum, maximum):
        diff = maximum - minimum + 1
        if diff <= 0:
            return maximum
        return (self.generate() % diff) + minimum