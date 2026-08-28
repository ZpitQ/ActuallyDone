package com.example.petstore;

public class PetStoreException extends RuntimeException {

    private final int status;

    public PetStoreException(int status, String message) {
        super(message);
        this.status = status;
    }

    public int getStatus() {
        return status;
    }
}
