from hop_transfer import HopTransfer

if __name__ == "__main__":
    rpc_url = ""
    sender_priv_base58_str = ""
    receiver_pubkey_str = ""
    sol_amount = 0.1

    hop_transfer = HopTransfer(rpc_url, sender_priv_base58_str, receiver_pubkey_str, sol_amount)

    try:
        complete = hop_transfer.execute()
        if complete: 
            print("Hop transfer complete.")
        else:
            print("Hop transfer failed.")
        
    except Exception as e:
        print("Error during hop transfer:", e)
