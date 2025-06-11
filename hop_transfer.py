import json
import os
import time
from datetime import datetime
from typing import Optional

from solana.rpc.api import Client
from solana.rpc.commitment import Finalized, Confirmed
from solana.rpc.types import TxOpts

from spl.token.instructions import (
    CloseAccountParams,
    SyncNativeParams,
    close_account,
    create_associated_token_account,
    get_associated_token_address,
    sync_native,
)

from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price  # type: ignore
from solders.keypair import Keypair  # type: ignore
from solders.message import MessageV0  # type: ignore
from solders.pubkey import Pubkey  # type: ignore
from solders.signature import Signature  # type: ignore
from solders.system_program import TransferParams, transfer  # type: ignore
from solders.transaction import VersionedTransaction  # type: ignore

class HopTransfer:
    def __init__(
        self,
        rpc_url: str,
        sender_priv_base58_str: str,
        receiver_pubkey_str: str,
        sol_amount: float
    ):
        self.rpc_url = rpc_url
        self.sender_priv_base58_str = sender_priv_base58_str
        self.receiver_pubkey_str = receiver_pubkey_str
        self.sol_amount = sol_amount
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

    def transfer_sol(self, sol_amount: float):
        sender_keypair = Keypair.from_base58_string(self.sender_priv_base58_str)
        to_pubkey = Pubkey.from_string(self.hop_pub_str)
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
                opts=TxOpts(skip_preflight=True),
            ).value
            
            confirmed = self.confirm_txn(txn_sig, Finalized)
            return confirmed
        except Exception:
            return None

    def recover_sol(self, sol_in: float):
        token_program_id = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        wsol = Pubkey.from_string("So11111111111111111111111111111111111111112")
        
        payer_keypair = Keypair.from_base58_string(self.sender_priv_base58_str)
        wallet_keypair = Keypair.from_base58_string(self.hop_priv_str)
        dest = Pubkey.from_string(self.receiver_pubkey_str)

        wsol_token_account = get_associated_token_address(
            wallet_keypair.pubkey(),
            wsol,
            token_program_id,
        )

        print("Creating WSOL ata...")
        wsol_ata_ix = create_associated_token_account(
            payer_keypair.pubkey(),
            wallet_keypair.pubkey(),
            wsol,
            token_program_id,
        )

        print(f"Transferring {sol_in} SOL into WSOL ATA...")
        transfer_to_ata_ix = transfer(
            TransferParams(
                from_pubkey=wallet_keypair.pubkey(),
                to_pubkey=wsol_token_account,
                lamports=int(sol_in * 1e9),
            )
        )
        print("Sync native...")
        sync_ix = sync_native(
            SyncNativeParams(
                program_id=token_program_id,
                account=wsol_token_account,
            )
        )

        print("Preparing to close WSOL account...")
        close_wsol_account_instruction = close_account(
            CloseAccountParams(
                program_id=token_program_id,
                account=wsol_token_account,
                dest=dest,
                owner=wallet_keypair.pubkey(),
            )
        )

        instructions = [
            set_compute_unit_limit(100_000),
            set_compute_unit_price(50_000),
            wsol_ata_ix,
            transfer_to_ata_ix,
            sync_ix,
            close_wsol_account_instruction
        ]

        print("Compiling transaction message...")
        compiled_message = MessageV0.try_compile(
            payer_keypair.pubkey(),
            instructions,
            [],
            self.client.get_latest_blockhash().value.blockhash,
        )
        try:
            print("Sending transaction...")
            txn_sig = self.client.send_transaction(
                txn=VersionedTransaction(compiled_message, [payer_keypair, wallet_keypair]),
                opts=TxOpts(skip_preflight=True)
            ).value
            
            confirmed = self.confirm_txn(txn_sig, Confirmed)
            return confirmed

        except Exception as e:
            print("Error occurred during transaction:", e)
            return False

    def wait_for_balance(self, max_retries: int = 10, retry_interval: float = 3.0) -> float:
        attempt = 1
        while attempt <= max_retries:
            try:
                lamports = self.client.get_balance(Pubkey.from_string(self.hop_pub_str)).value
                sol = lamports / 1e9
                if sol > 0:
                    print(f"Balance detected: {sol:.9f} SOL (after {attempt} attempt(s))")
                    return sol
                print(f"Attempt {attempt}/{max_retries}: balance is zero, retrying in {retry_interval}s…")
            except Exception as e:
                print(f"Attempt {attempt}/{max_retries} RPC error: {e!r}")
            if attempt < max_retries:
                time.sleep(retry_interval)
            attempt += 1
        raise RuntimeError(f"Balance still zero after {max_retries} attempts...")

    def confirm_txn(self, txn_sig: Signature, commitment, max_retries: int = 20, retry_interval: int = 3) -> bool:
        retries = 1
        while retries < max_retries:
            try:
                txn_res = self.client.get_transaction(
                    txn_sig,
                    encoding="json",
                    commitment=commitment,
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

    def execute(self) -> bool:
        if not (self.hop_pub_str and self.hop_priv_str):
            raise RuntimeError("Hop wallet not created. Call create_hop_wallet() first.")
        start_ts = time.time()
        
        transfer_ok = self.transfer_sol(self.sol_amount)
        if not transfer_ok:
            raise RuntimeError("Failed to send to hop wallet.")

        hop_balance = self.wait_for_balance()
        recover_ok = self.recover_sol(hop_balance)
        if not recover_ok:
            raise RuntimeError("Failed to recover SOL from hop wallet.")

        elapsed = time.time() - start_ts
        print(f"Elapsed Time: {elapsed}")
        return recover_ok

    def save_hop_keys(self, save_dir: str = ".", timestamp_format: str = "%Y%m%d_%H%M%S") -> str:
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
