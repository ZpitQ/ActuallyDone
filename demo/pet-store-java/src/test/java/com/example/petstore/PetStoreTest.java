package com.example.petstore;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.math.BigDecimal;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;

@Execution(ExecutionMode.CONCURRENT)
class PetStoreTest {

    @Test
    void registerKeepsAvailablePet() {
        PetStore store = new PetStore();
        Pet pet = store.register("Mochi", "cat", new BigDecimal("12.50"));
        assertEquals("Mochi", pet.getName());
        assertEquals("cat", pet.getSpecies());
        assertEquals(0, pet.getPrice().compareTo(new BigDecimal("12.50")));
        assertEquals(PetStatus.AVAILABLE, pet.getStatus());
        assertEquals(1, store.list().size());
    }

    @Test
    void rejectsBlankName() {
        PetStore store = new PetStore();
        PetStoreException e = assertThrows(PetStoreException.class,
                () -> store.register("  ", "dog", new BigDecimal("8")));
        assertEquals(400, e.getStatus());
        assertTrue(e.getMessage().contains("name"));
    }

    @Test
    void rejectsUnknownSpecies() {
        PetStore store = new PetStore();
        PetStoreException e = assertThrows(PetStoreException.class,
                () -> store.register("Rex", "dragon", new BigDecimal("8")));
        assertEquals(400, e.getStatus());
        assertTrue(e.getMessage().contains("species"));
    }

    @Test
    void rejectsNegativePrice() {
        PetStore store = new PetStore();
        PetStoreException e = assertThrows(PetStoreException.class,
                () -> store.register("Nemo", "fish", new BigDecimal("-1")));
        assertEquals(400, e.getStatus());
        assertTrue(e.getMessage().contains("price"));
    }

    @Test
    void buyMarksPetSold() {
        PetStore store = new PetStore();
        Pet pet = store.register("Kiwi", "bird", new BigDecimal("20"));
        Pet sold = store.buy(pet.getId());
        assertEquals(PetStatus.SOLD, sold.getStatus());
        assertEquals(PetStatus.SOLD, store.get(pet.getId()).getStatus());
    }

    @Test
    void buySoldPetIsRejected() {
        PetStore store = new PetStore();
        Pet pet = store.register("Kiwi", "bird", new BigDecimal("20"));
        store.buy(pet.getId());
        PetStoreException e = assertThrows(PetStoreException.class, () -> store.buy(pet.getId()));
        assertEquals(409, e.getStatus());
        assertTrue(e.getMessage().contains("already sold"));
    }

    @Test
    void missingPetIsNotFound() {
        PetStore store = new PetStore();
        PetStoreException e = assertThrows(PetStoreException.class, () -> store.get(99));
        assertEquals(404, e.getStatus());
    }

    private static final Set<String> WORKERS = ConcurrentHashMap.newKeySet();
    private static final CountDownLatch BOTH = new CountDownLatch(4);

    @Test
    void parallelWorkerA() throws InterruptedException {
        rendezvous();
        assertTrue(WORKERS.size() >= 4);
    }

    @Test
    void parallelWorkerB() throws InterruptedException {
        rendezvous();
        assertTrue(WORKERS.size() >= 4);
    }

    @Test
    void parallelWorkerC() throws InterruptedException {
        rendezvous();
        assertTrue(WORKERS.size() >= 4);
    }

    @Test
    void parallelWorkerD() throws InterruptedException {
        rendezvous();
        assertTrue(WORKERS.size() >= 4);
    }

    private static void rendezvous() throws InterruptedException {
        WORKERS.add(Thread.currentThread().getName());
        BOTH.countDown();
        assertTrue(BOTH.await(5, TimeUnit.SECONDS),
                "四条 UT 没能同时跑起来：JUnit 并行没生效，或线程池太小");
        assertTrue(WORKERS.size() >= 4,
                "工作线程不足 4 个 " + WORKERS + "，并发没有加大");
    }
}
