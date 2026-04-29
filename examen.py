from typing import List

def spell(word:str)->List[str]:
    """Get a string and return a list
    telling if every character in string is
    text or number as shown in test.
    """
    resultado = []
    for i in word:
        if i.isdigit():
            resultado.append(f"{i} is a number")
        else:
            resultado.append(f"{i} is a text")

    # implement this function to make
    # to make outcome variable True
    return resultado

# test
expected = spell('shalke 04')
print(expected)
outcome = expected == ['s is text', 'h is text', 'a is text', 'l is text', 'k is text', 'e is text', '  is text', '0 is number', '4 is number']
print(outcome)