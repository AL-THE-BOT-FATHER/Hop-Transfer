from hop_transfer import HopTransfer

if __name__ == "__main__":
    rpc_url = ""
    sender_priv_base58_str = ""
    receiver_pubkey_str = ""
    sol_amount = 0.10

    hop_transfer = HopTransfer(rpc_url, sender_priv_base58_str, receiver_pubkey_str)

    try:
        results = hop_transfer.execute(sol_amount)
        print("\n=== Transaction Links ===")
        print("1) to_hop:", results["to_hop"])
        print("2) to_receiver:", results["to_receiver"])
        print("3) recover_hop:", results["recover_hop"])
    except Exception as e:
        print("❌ Error during hoped transfer:", e)
