import pytest
import brownie
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_structured_data


@pytest.fixture
def vault(gov, token, Vault):
    # NOTE: Overriding the one in conftest because it has values already
    yield gov.deploy(Vault, token, gov, gov, "", "")


def test_deposit_with_zero_funds(vault, token, rando):
    assert token.balanceOf(rando) == 0
    token.approve(vault, 2 ** 256 - 1, {"from": rando})
    with brownie.reverts():
        vault.deposit({"from": rando})


def test_deposit_with_wrong_amount(vault, token, gov):
    balance = token.balanceOf(gov) + 1
    token.approve(vault, balance, {"from": gov})
    with brownie.reverts():
        vault.deposit(balance, {"from": gov})


def test_deposit_all_and_withdraw_all(gov, vault, token):
    balance = token.balanceOf(gov)
    token.approve(vault, token.balanceOf(gov), {"from": gov})
    vault.deposit({"from": gov})
    # vault has tokens
    assert token.balanceOf(vault) == balance
    # sender has vault shares
    assert vault.balanceOf(gov) == balance

    vault.withdraw({"from": gov})
    # vault no longer has tokens
    assert token.balanceOf(vault) == 0
    # sender no longer has shares
    assert vault.balanceOf(gov) == 0
    # sender has tokens
    assert token.balanceOf(gov) == balance


def test_deposit_withdraw(gov, vault, token, fn_isolation):
    balance = token.balanceOf(gov)
    token.approve(vault, balance, {"from": gov})
    vault.deposit(balance // 2, {"from": gov})

    assert token.balanceOf(vault) == balance // 2
    assert vault.totalDebt() == 0
    assert vault.pricePerShare() == 10 ** token.decimals()  # 1:1 price

    # Do it twice to test behavior when it has shares
    vault.deposit({"from": gov})

    assert vault.totalSupply() == token.balanceOf(vault) == balance
    assert vault.totalDebt() == 0
    assert vault.pricePerShare() == 10 ** token.decimals()  # 1:1 price

    vault.withdraw(vault.balanceOf(gov) // 2, {"from": gov})

    assert token.balanceOf(vault) == balance // 2
    assert vault.totalDebt() == 0
    assert vault.pricePerShare() == 10 ** token.decimals()  # 1:1 price

    # Can't withdraw more shares than we have
    with brownie.reverts():
        vault.withdraw(2 * vault.balanceOf(gov), {"from": gov})

    vault.withdraw({"from": gov})
    assert vault.totalSupply() == token.balanceOf(vault) == 0
    assert vault.totalDebt() == 0
    assert token.balanceOf(gov) == balance

    vault.setDepositLimit(0, {"from": gov})

    # Deposits are locked out
    with brownie.reverts():
        vault.deposit({"from": gov})


def test_delegated_deposit_withdraw(accounts, token, vault, fn_isolation):
    a, b, c, d, e = accounts[0:5]

    # Store original amount of tokens so we can assert
    # Number of tokens will be equal to number of shares since no returns are generated
    originalTokenAmount = token.balanceOf(a)

    # Make sure we have tokens to play with
    assert originalTokenAmount > 0

    # 1. Deposit from a and send shares to b
    token.approve(vault, token.balanceOf(a), {"from": a})
    vault.deposit(token.balanceOf(a), b, {"from": a})

    # a no longer has any tokens
    assert token.balanceOf(a) == 0
    # a does not have any vault shares
    assert vault.balanceOf(a) == 0
    # b has been issued the vault shares
    assert vault.balanceOf(b) == originalTokenAmount

    # 2. Withdraw from b to c
    vault.withdraw(vault.balanceOf(b), c, {"from": b})

    # b no longer has any shares
    assert vault.balanceOf(b) == 0
    # b did not receive the tokens
    assert token.balanceOf(b) == 0
    # c has the tokens
    assert token.balanceOf(c) == originalTokenAmount

    # 3. Deposit all from c and send shares to d
    token.approve(vault, token.balanceOf(c), {"from": c})
    vault.deposit(token.balanceOf(c), d, {"from": c})

    # c no longer has the tokens
    assert token.balanceOf(c) == 0
    # c does not have any vault shares
    assert vault.balanceOf(c) == 0
    # d has been issued the vault shares
    assert vault.balanceOf(d) == originalTokenAmount

    # 4. Withdraw from d to e
    vault.withdraw(vault.balanceOf(d), e, {"from": d})

    # d no longer has any shares
    assert vault.balanceOf(d) == 0
    # d did not receive the tokens
    assert token.balanceOf(d) == 0
    # e has the tokens
    assert token.balanceOf(e) == originalTokenAmount


def test_emergencyShutdown(gov, vault, token, fn_isolation):
    balance = token.balanceOf(gov)
    token.approve(vault, balance, {"from": gov})
    vault.deposit(balance // 2, {"from": gov})

    assert token.balanceOf(vault) == balance // 2
    assert vault.totalDebt() == 0
    assert vault.pricePerShare() == 10 ** token.decimals()  # 1:1 price

    vault.setEmergencyShutdown(True, {"from": gov})

    # Deposits are locked out
    with brownie.reverts():
        vault.deposit({"from": gov})

    # But withdrawals are fine
    vault.withdraw(vault.balanceOf(gov), {"from": gov})
    assert token.balanceOf(vault) == 0
    assert token.balanceOf(gov) == balance


def test_transfer(accounts, token, vault, fn_isolation):
    a, b = accounts[0:2]
    token.approve(vault, token.balanceOf(a), {"from": a})
    vault.deposit({"from": a})

    assert vault.balanceOf(a) == token.balanceOf(vault)
    assert vault.balanceOf(b) == 0

    # Can't send your balance to the Vault
    with brownie.reverts():
        vault.transfer(vault, vault.balanceOf(a), {"from": a})

    # Can't send your balance to the zero address
    with brownie.reverts():
        vault.transfer(
            "0x0000000000000000000000000000000000000000",
            vault.balanceOf(a),
            {"from": a},
        )

    vault.transfer(b, vault.balanceOf(a), {"from": a})

    assert vault.balanceOf(a) == 0
    assert vault.balanceOf(b) == token.balanceOf(vault)


def test_transferFrom(accounts, token, vault, fn_isolation):
    a, b, c = accounts[0:3]
    token.approve(vault, token.balanceOf(a), {"from": a})
    vault.deposit({"from": a})

    # Unapproved can't send
    with brownie.reverts():
        vault.transferFrom(a, b, vault.balanceOf(a) // 2, {"from": c})

    vault.approve(c, vault.balanceOf(a) // 2, {"from": a})
    assert vault.allowance(a, c) == vault.balanceOf(a) // 2

    vault.increaseAllowance(c, vault.balanceOf(a) // 2, {"from": a})
    assert vault.allowance(a, c) == vault.balanceOf(a)

    vault.decreaseAllowance(c, vault.balanceOf(a) // 2, {"from": a})
    assert vault.allowance(a, c) == vault.balanceOf(a) // 2

    # Can't send more than what is approved
    with brownie.reverts():
        vault.transferFrom(a, b, vault.balanceOf(a), {"from": c})

    assert vault.balanceOf(a) == token.balanceOf(vault)
    assert vault.balanceOf(b) == 0

    vault.transferFrom(a, b, vault.balanceOf(a) // 2, {"from": c})

    assert vault.balanceOf(a) == token.balanceOf(vault) // 2
    assert vault.balanceOf(b) == token.balanceOf(vault) // 2

    # If approval is unlimited, little bit of a gas savings
    vault.approve(c, 2 ** 256 - 1, {"from": a})
    vault.transferFrom(a, b, vault.balanceOf(a), {"from": c})

    assert vault.balanceOf(a) == 0
    assert vault.balanceOf(b) == token.balanceOf(vault)


def test_permit(vault, token, accounts, chain):
    # Account A will be doing the permit(), so we'll need to generate a signature
    a = accounts.add()  # Generates a LocalAccount with an attached privateKey
    b = accounts[1]

    signingAccount = Account.from_key(a.private_key)

    assert vault.nonces(a) == 0
    assert vault.allowance(a, b) == 0

    permitMessage = encode_structured_data(
        {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Permit": [
                    {"name": "holder", "type": "address"},
                    {"name": "spender", "type": "address"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "expiry", "type": "uint256"},
                    {"name": "allowed", "type": "bool"},
                ],
            },
            "primaryType": "Permit",
            "domain": {
                "name": vault.name(),
                "version": vault.apiVersion(),
                "chainId": chain.id,
                "verifyingContract": vault.address,
            },
            "message": {
                "holder": a.address,
                "spender": b.address,
                "nonce": 0,
                "expiry": 0,
                "allowed": True,
            },
        }
    )

    signedMessage = signingAccount.sign_message(permitMessage)

    vault.permit(a, b, 1, 0, True, signedMessage.v, signedMessage.r, signedMessage.s)

    assert vault.allowance(a, b) == 2 ^ 256 - 1  # MAX_UINT256 in Vyper
    assert vault.nonce(a) == 1
