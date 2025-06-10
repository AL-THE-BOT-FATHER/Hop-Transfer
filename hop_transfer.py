from datetime import datetime
import json
import os
from typing import Callable, Dict, Optional
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solders.compute_budget import set_compute_unit_price, set_compute_unit_limit  # type: ignore
from solders.keypair import Keypair  # type: ignore
from solders.pubkey import Pubkey  # type: ignore
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction  # type: ignore
from solders.message import MessageV0  # type: ignore
import time
from solana.rpc.commitment import Finalized
from solders.signature import Signature  # type: ignore


class HopTransfer:
    def __init__(
        self,
        rpc_url: str,
        sender_priv_base58_str: str,
        receiver_pubkey_str: str,
    ):
        self.rpc_url = rpc_url
        self.sender_priv_base58_str = sender_priv_base58_str
        self.receiver_pubkey_str = receiver_pubkey_str
        self.client = Client(rpc_url)
        self.hop_pub_str: Optional[str] = None
        self.hop_priv_str: Optional[str] = None
        self.create_hop_wallet()
        self.save_hop_keys()

    def create_hop_wallet(self):
        keypair = Keypair()
        self.hop_priv_str = str(keypair)
        self.hop_pub_str = str(keypair.pubkey())
        return self.hop_pub_str, self.hop_priv_str

    def transfer_sol(
        self,
        sender_priv_base58_str: str,
        receiver_pubkey_str: str,
        sol_amount: float,
    ):
        sender_keypair = Keypair.from_base58_string(sender_priv_base58_str)
        to_pubkey = Pubkey.from_string(receiver_pubkey_str)
        lamports_amount = int(sol_amount * 1e9)
        sender_balance = self.client.get_balance(sender_keypair.pubkey()).value
        if sender_balance < lamports_amount:
            return "Insufficient balance for the transaction."
        instructions = [
            set_compute_unit_price(100_000),
            set_compute_unit_limit(10_000),
            transfer(
                TransferParams(
                    from_pubkey=sender_keypair.pubkey(),
                    to_pubkey=to_pubkey,
                    lamports=lamports_amount,
                )
            )
        ]
        recent_blockhash = self.client.get_latest_blockhash().value.blockhash
        compiled_message = MessageV0.try_compile(
            sender_keypair.pubkey(),
            instructions,
            [],
            recent_blockhash,
        )
        try:
            txn_sig = self.client.send_transaction(
                txn=VersionedTransaction(compiled_message, [sender_keypair]),
                opts=TxOpts(skip_preflight=False),
            ).value
            return txn_sig
        except Exception:
            return None

    def recover_sol(
        self,
        sender_priv_base58_str: str,
        receiver_priv_base58_str: str
    ) -> Optional[bool]:
        sender_keypair = Keypair.from_base58_string(sender_priv_base58_str)
        receiver_keypair = Keypair.from_base58_string(receiver_priv_base58_str)
        sender_balance = self.client.get_balance(sender_keypair.pubkey()).value
        if sender_balance == 0:
            return "❌ Insufficient balance for the transaction."
        instructions = [
            set_compute_unit_price(100_000),
            set_compute_unit_limit(10_000),
            transfer(
                TransferParams(
                    from_pubkey=sender_keypair.pubkey(),
                    to_pubkey=receiver_keypair.pubkey(),
                    lamports=sender_balance,
                )
            )
        ]
        recent_blockhash = self.client.get_latest_blockhash().value.blockhash
        compiled_message = MessageV0.try_compile(
            receiver_keypair.pubkey(),
            instructions,
            [],
            recent_blockhash,
        )
        try:
            txn_sig = self.client.send_transaction(
                txn=VersionedTransaction(compiled_message, [sender_keypair, receiver_keypair]),
                opts=TxOpts(skip_preflight=True),
            ).value
            return txn_sig
        except Exception:
            return None

    def wait_for_balance(
        self,
        pub_key: str,
        max_retries: int = 5,
        retry_interval: float = 1.0,
    ) -> float:
        to_pubkey = Pubkey.from_string(pub_key)
        attempt = 1
        while attempt <= max_retries:
            try:
                lamports = self.client.get_balance(to_pubkey).value
                return lamports / 1e9
            except Exception as e:
                print(f"check_balance attempt {attempt}/{max_retries} failed: {e}")
                if attempt == max_retries:
                    raise RuntimeError("Failed to fetch balance after multiple retries")
                time.sleep(retry_interval)
                attempt += 1

    def confirm_txn(
        self,
        txn_sig: Signature,
        max_retries: int = 20,
        retry_interval: int = 3
    ) -> bool:
        retries = 1
        while retries < max_retries:
            try:
                txn_res = self.client.get_transaction(
                    txn_sig,
                    encoding="json",
                    commitment=Finalized,
                    max_supported_transaction_version=0
                )
                txn_json = json.loads(txn_res.value.transaction.meta.to_json())
                if txn_json['err'] is None:
                    print("Transaction confirmed... try count:", retries)
                    return True
                print("Error: Transaction not confirmed. Retrying...")
                if txn_json['err']:
                    print("Transaction failed.")
                    return False
            except Exception:
                print("Awaiting confirmation... try count:", retries)
            retries += 1
            time.sleep(retry_interval)
        print("Max retries reached. Transaction confirmation failed.")
        return None

    def retry_confirm(
        self,
        action_fn: Callable[..., str],
        confirm_fn: Callable[[Signature], bool],
        description: str,
        *action_args,
        max_attempts: int = 3,
        delay: float = 1,
    ) -> str:
        for attempt in range(1, max_attempts + 1):
            print(f"→ Attempt {attempt}: {description}")
            try:
                sig = action_fn(*action_args)
                if confirm_fn(sig):
                    return sig
                print("   ✗ Confirmation failed.")
            except Exception as e:
                print(f"   ✗ Error: {e}")
            if attempt == max_attempts:
                raise RuntimeError(f"{description} failed after {max_attempts} attempts.")
            time.sleep(delay)

    def execute(
        self,
        sol_amount: float,
        txn_fee_hop: float = 0.01,
    ) -> Dict[str, str]:
        if not (self.hop_pub_str and self.hop_priv_str):
            raise RuntimeError("Hop wallet not created. Call create_hop_wallet() first.")
        start_time = time.time()
        total_amount = sol_amount + txn_fee_hop

        sig1 = self.retry_confirm(
            lambda priv, pub, amt: self.transfer_sol(priv, pub, amt),
            self.confirm_txn,
            f"Sending {total_amount} SOL into hop {self.hop_pub_str}",
            self.sender_priv_base58_str,
            self.hop_pub_str,
            total_amount,
            max_attempts=3,
            delay=1,
        )

        bal = self.wait_for_balance(self.hop_pub_str)
        if bal < sol_amount:
            raise RuntimeError(f"Hop balance too low: {bal} SOL (need {sol_amount} SOL)")

        sig2 = self.retry_confirm(
            lambda priv, pub, amt: self.transfer_sol(priv, pub, amt),
            self.confirm_txn,
            f"Sending {sol_amount} SOL from hop to receiver {self.receiver_pubkey_str}",
            self.hop_priv_str,
            self.receiver_pubkey_str,
            sol_amount,
            max_attempts=3,
            delay=1,
        )

        print("→ Waiting 5 seconds before recovering leftover...")
        time.sleep(5)

        sig3 = self.retry_confirm(
            lambda priv_s, priv_r: self.recover_sol(priv_s, priv_r),
            self.confirm_txn,
            f"Recovering leftover SOL from hop to sender",
            self.hop_priv_str,
            self.sender_priv_base58_str,
            max_attempts=3,
            delay=1,
        )

        elapsed = time.time() - start_time
        print(f"→ Completed in {elapsed:.2f}s")

        return {
            "to_hop":      sig1,
            "to_receiver":    sig2,
            "recover_hop": sig3,
        }

    def save_hop_keys(
        self,
        save_dir: str = ".",
        timestamp_format: str = "%Y%m%d_%H%M%S"
    ) -> str:
        if not (self.hop_pub_str and self.hop_priv_str):
            raise RuntimeError("Hop wallet not created. Call create_hop_wallet() first.")
        if save_dir and not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)
        now = datetime.now().strftime(timestamp_format)
        filename = f"hop_keys_{now}.txt"
        file_path = os.path.join(save_dir, filename)
        with open(file_path, "w") as f:
            f.write(f"PUBKEY={self.hop_pub_str}\n")
            f.write(f"PRIVKEY={self.hop_priv_str}\n")
        print(f"Saved hop keys to {file_path}")
        return file_path

